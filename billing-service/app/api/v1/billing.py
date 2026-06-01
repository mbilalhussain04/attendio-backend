from datetime import datetime, timedelta, timezone
from typing import Literal

import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.deps.auth import AuthContext, get_auth_context, require_billing_admin
from app.models.billing import BillingCustomer, BillingEvent, BillingInvoice, BillingLicense, BillingSubscription
from app.providers.base import ProviderNotConfigured, get_plans
from app.providers.factory import get_provider

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan_key: str


class ChangePlanRequest(BaseModel):
    plan_key: str


class StatusUpdateRequest(BaseModel):
    status: Literal["trialing", "active", "past_due", "unpaid", "canceled", "expired"]


class ActivateLicenseRequest(BaseModel):
    license_key: str


class AttachPaymentMethodRequest(BaseModel):
    brand: str
    last4: str
    exp_month: int
    exp_year: int
    billing_email: str | None = None
    holder_name: str | None = None


FREE_LIMITS = {
    "branches": 1,
    "projects": 1,
    "employees": 10,
    "downloads": 0,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def plan_payload(plan):
    return {
        "key": plan.key,
        "name": plan.name,
        "price_cents": plan.price_cents,
        "currency": settings.BILLING_CURRENCY,
        "interval": plan.interval,
        "included_employees": plan.included_employees,
        "description": plan.description,
    }


def license_hash(key: str) -> str:
    return hashlib.sha256(key.strip().upper().encode("utf-8")).hexdigest()


def generate_license_key() -> str:
    return f"ATD-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"


def get_or_create_license(db: Session, company_id: str) -> tuple[BillingLicense, str | None]:
    license_row = db.execute(select(BillingLicense).where(BillingLicense.company_id == company_id)).scalar_one_or_none()
    if license_row:
        return license_row, None
    raw_key = generate_license_key()
    license_row = BillingLicense(
        company_id=company_id,
        license_key_hash=license_hash(raw_key),
        license_key_prefix=raw_key.split("-", 2)[0],
        license_key_last4=raw_key[-4:],
        status="allocated",
        seats=settings.STANDARD_PLAN_INCLUDED_LICENSES,
    )
    db.add(license_row)
    db.commit()
    db.refresh(license_row)
    return license_row, raw_key


def get_or_create_subscription(db: Session, company_id: str) -> BillingSubscription:
    subscription = db.execute(
        select(BillingSubscription).where(BillingSubscription.company_id == company_id)
    ).scalar_one_or_none()
    if subscription:
        return subscription
    now = utc_now()
    subscription = BillingSubscription(
        company_id=company_id,
        plan_key="free",
        status="trialing",
        provider=settings.BILLING_PROVIDER,
        trial_start=now,
        trial_end=now + timedelta(days=max(settings.TRIAL_DAYS, 0)),
        current_period_start=now,
        current_period_end=now + timedelta(days=max(settings.TRIAL_DAYS, 0)),
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def get_customer(db: Session, company_id: str, provider: str) -> BillingCustomer | None:
    return db.execute(
        select(BillingCustomer).where(
            BillingCustomer.company_id == company_id,
            BillingCustomer.provider == provider,
        )
    ).scalar_one_or_none()


def serialize_customer(customer: BillingCustomer | None) -> dict:
    if not customer:
        return {
            "provider": settings.BILLING_PROVIDER,
            "status": "not_linked",
            "billing_email": None,
            "has_provider_customer": False,
            "payment_method": None,
        }
    payment_method = None
    if customer.payment_method_last4:
        payment_method = {
            "brand": customer.payment_method_brand,
            "last4": customer.payment_method_last4,
            "exp_month": customer.payment_method_exp_month,
            "exp_year": customer.payment_method_exp_year,
        }
    linked = bool(customer.provider_customer_id or customer.provider_payment_method_id)
    return {
        "provider": customer.provider,
        "status": "linked" if linked else "not_linked",
        "billing_email": customer.billing_email,
        "has_provider_customer": bool(customer.provider_customer_id),
        "payment_method": payment_method,
    }


def serialize_subscription(subscription: BillingSubscription) -> dict:
    now = utc_now()
    trial_end = subscription.trial_end
    if trial_end and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)
    trial_days_remaining = max(0, (trial_end - now).days) if trial_end else 0
    effective_status = subscription.status
    if subscription.status == "trialing" and trial_end and trial_end < now:
        effective_status = "expired"
    grace_until = subscription.current_period_end
    if grace_until and grace_until.tzinfo is None:
        grace_until = grace_until.replace(tzinfo=timezone.utc)
    if grace_until and effective_status in {"past_due", "unpaid"}:
        grace_until = grace_until + timedelta(days=max(settings.PAYMENT_GRACE_DAYS, 0))
    workspace_locked = settings.BILLING_ENABLED and (
        effective_status in {"expired"}
        or effective_status in {"past_due", "unpaid"} and bool(grace_until and grace_until < now)
        or effective_status == "canceled" and bool(subscription.current_period_end and subscription.current_period_end < now)
    )
    requires_payment = settings.BILLING_ENABLED and effective_status in {"expired", "past_due", "unpaid", "canceled"}
    return {
        "id": subscription.id,
        "plan_key": subscription.plan_key,
        "status": effective_status,
        "stored_status": subscription.status,
        "provider": subscription.provider,
        "billing_enabled": settings.BILLING_ENABLED,
        "trial_start": subscription.trial_start.isoformat() if subscription.trial_start else None,
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "trial_days_remaining": trial_days_remaining,
        "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
        "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "requires_payment": requires_payment,
        "grace_until": grace_until.isoformat() if grace_until else None,
        "access": {
            "workspace_locked": workspace_locked,
            "payment_action_required": requires_payment,
            "message": "Payment failed. Update payment method before the grace period ends." if effective_status in {"past_due", "unpaid"} else "Subscription is not active." if workspace_locked else None,
        },
    }


def serialize_license(license_row: BillingLicense, raw_key: str | None = None) -> dict:
    expires_at = license_row.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    expired = bool(expires_at and expires_at < utc_now())
    status = "expired" if license_row.status == "active" and expired else license_row.status
    return {
        "id": license_row.id,
        "status": status,
        "seats": license_row.seats,
        "license_key": raw_key,
        "masked_key": f"{license_row.license_key_prefix}-****-****-{license_row.license_key_last4}",
        "activated_at": license_row.activated_at.isoformat() if license_row.activated_at else None,
        "expires_at": license_row.expires_at.isoformat() if license_row.expires_at else None,
    }


def activate_license_for_period(license_row: BillingLicense, subscription: BillingSubscription) -> None:
    license_row.status = "active"
    license_row.seats = next((plan.included_employees or license_row.seats for plan in get_plans() if plan.key == subscription.plan_key), license_row.seats)
    license_row.activated_at = license_row.activated_at or utc_now()
    license_row.expires_at = subscription.current_period_end or (utc_now() + timedelta(days=30))


def entitlements_for(subscription: BillingSubscription, license_row: BillingLicense | None = None) -> dict:
    serialized = serialize_subscription(subscription)
    enabled = settings.BILLING_ENABLED
    if not enabled:
        return {
            "enabled": False,
            "plan_key": subscription.plan_key,
            "mode": "unrestricted",
            "limits": {"branches": None, "projects": None, "employees": None, "downloads": None},
            "can_download": True,
            "workspace_locked": False,
        }
    active_license = False
    if license_row:
        license_payload = serialize_license(license_row)
        active_license = license_payload["status"] == "active"
    standard_active = subscription.plan_key == "standard" and subscription.status in {"active", "trialing"} and active_license and not serialized["access"]["workspace_locked"]
    if standard_active:
        return {
            "enabled": True,
            "plan_key": "standard",
            "mode": "standard",
            "limits": {"branches": None, "projects": None, "employees": license_row.seats if license_row else settings.STANDARD_PLAN_INCLUDED_LICENSES, "downloads": None},
            "can_download": True,
            "workspace_locked": False,
        }
    return {
        "enabled": True,
        "plan_key": subscription.plan_key or "free",
        "mode": "free",
        "limits": FREE_LIMITS,
        "can_download": False,
        "workspace_locked": serialized["access"]["workspace_locked"],
    }


@router.get("/plans")
def plans():
    return {"message": "Billing plans fetched", "data": [plan_payload(plan) for plan in get_plans()]}


@router.get("/status")
def status(db: Session = Depends(get_db), auth: AuthContext = Depends(get_auth_context)):
    subscription = get_or_create_subscription(db, auth.company_id)
    license_row, raw_key = get_or_create_license(db, auth.company_id)
    invoices = db.execute(
        select(BillingInvoice)
        .where(BillingInvoice.company_id == auth.company_id)
        .order_by(BillingInvoice.created_at.desc())
        .limit(5)
    ).scalars().all()
    return {
        "message": "Billing status fetched",
        "data": {
            "subscription": serialize_subscription(subscription),
            "license": serialize_license(license_row, raw_key),
            "entitlements": entitlements_for(subscription, license_row),
            "customer": serialize_customer(get_customer(db, auth.company_id, settings.BILLING_PROVIDER)),
            "plans": [plan_payload(plan) for plan in get_plans()],
            "recent_invoices": [serialize_invoice(invoice) for invoice in invoices],
        },
    }


@router.get("/internal/entitlements/{company_id}")
def internal_entitlements(company_id: str, request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("x-internal-service-token")
    if token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal service token")
    subscription = get_or_create_subscription(db, company_id)
    license_row, _ = get_or_create_license(db, company_id)
    return {"message": "Billing entitlements fetched", "data": {"subscription": serialize_subscription(subscription), "license": serialize_license(license_row), "entitlements": entitlements_for(subscription, license_row)}}


@router.get("/invoices")
def invoices(db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    rows = db.execute(
        select(BillingInvoice)
        .where(BillingInvoice.company_id == auth.company_id)
        .order_by(BillingInvoice.created_at.desc())
        .limit(100)
    ).scalars().all()
    return {"message": "Invoices fetched", "data": [serialize_invoice(row) for row in rows]}


@router.post("/checkout")
def checkout(payload: CheckoutRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    if payload.plan_key not in {plan.key for plan in get_plans()}:
        raise HTTPException(status_code=422, detail="Unknown billing plan")
    if payload.plan_key == "free":
        subscription = get_or_create_subscription(db, auth.company_id)
        subscription.plan_key = "free"
        subscription.status = "trialing"
        db.commit()
        return {"message": "Free plan selected", "data": {"provider": "manual", "mode": "free", "url": None}}
    get_or_create_subscription(db, auth.company_id)
    customer = get_customer(db, auth.company_id, settings.BILLING_PROVIDER)
    try:
        session = get_provider().create_checkout_session(
            company_id=auth.company_id,
            plan_key=payload.plan_key,
            success_url=settings.BILLING_SUCCESS_URL,
            cancel_url=settings.BILLING_CANCEL_URL,
            customer_id=customer.provider_customer_id if customer else None,
        )
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"message": "Checkout session created", "data": session}


@router.post("/portal")
def portal(db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    customer = get_customer(db, auth.company_id, settings.BILLING_PROVIDER)
    try:
        session = get_provider().create_customer_portal_session(
            company_id=auth.company_id,
            return_url=settings.BILLING_CANCEL_URL,
            customer_id=customer.provider_customer_id if customer else None,
        )
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"message": "Billing portal session created", "data": session}


@router.post("/payment-method")
def attach_payment_method(payload: AttachPaymentMethodRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    brand = payload.brand.strip().lower()
    if brand not in {"visa", "mastercard", "amex", "discover", "diners", "jcb", "card"} or not payload.last4.isdigit() or len(payload.last4) != 4:
        raise HTTPException(status_code=422, detail="Invalid card metadata")
    now = utc_now()
    if (
        payload.exp_month < 1
        or payload.exp_month > 12
        or payload.exp_year < now.year
        or payload.exp_year == now.year and payload.exp_month < now.month
        or payload.exp_year > now.year + 20
    ):
        raise HTTPException(status_code=422, detail="Invalid card expiry")
    customer = get_customer(db, auth.company_id, settings.BILLING_PROVIDER)
    if not customer:
        customer = BillingCustomer(company_id=auth.company_id, provider=settings.BILLING_PROVIDER)
        db.add(customer)
    customer.billing_email = payload.billing_email or customer.billing_email
    customer.provider_payment_method_id = customer.provider_payment_method_id or f"local-{auth.company_id}"
    customer.payment_method_brand = brand
    customer.payment_method_last4 = payload.last4
    customer.payment_method_exp_month = payload.exp_month
    customer.payment_method_exp_year = payload.exp_year
    db.commit()
    db.refresh(customer)
    return {"message": "Payment method saved", "data": {"customer": serialize_customer(customer)}}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    event = parse_stripe_event(body, request.headers.get("stripe-signature"))
    event_type = event.get("type") or "unknown"
    data_object = event.get("data", {}).get("object", {})
    company_id = resolve_company_from_stripe_object(db, data_object)
    db.add(BillingEvent(
        company_id=company_id,
        provider="stripe",
        event_type=event_type,
        provider_event_id=event.get("id"),
        payload_json=json.dumps(event),
    ))
    if company_id:
        apply_stripe_event(db, company_id, event_type, data_object)
    db.commit()
    return {"received": True}


@router.post("/change-plan")
def change_plan(payload: ChangePlanRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    if payload.plan_key not in {plan.key for plan in get_plans()}:
        raise HTTPException(status_code=422, detail="Unknown billing plan")
    subscription = get_or_create_subscription(db, auth.company_id)
    subscription.plan_key = payload.plan_key
    subscription.provider = settings.BILLING_PROVIDER
    db.commit()
    try:
        provider_response = get_provider().change_plan(company_id=auth.company_id, plan_key=payload.plan_key)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"message": "Plan updated", "data": {"subscription": serialize_subscription(subscription), "provider": provider_response}}


@router.post("/license/activate")
def activate_license(payload: ActivateLicenseRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    license_row, _ = get_or_create_license(db, auth.company_id)
    if license_row.license_key_hash != license_hash(payload.license_key):
        raise HTTPException(status_code=422, detail="Invalid license key")
    subscription = get_or_create_subscription(db, auth.company_id)
    if subscription.status not in {"active", "trialing"} or subscription.plan_key == "free":
        raise HTTPException(status_code=402, detail="Payment is required before activating this license")
    activate_license_for_period(license_row, subscription)
    db.commit()
    db.refresh(license_row)
    return {"message": "License activated", "data": serialize_license(license_row)}


@router.post("/license/rotate")
def rotate_license(db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    license_row, _ = get_or_create_license(db, auth.company_id)
    raw_key = generate_license_key()
    license_row.license_key_hash = license_hash(raw_key)
    license_row.license_key_prefix = raw_key.split("-", 2)[0]
    license_row.license_key_last4 = raw_key[-4:]
    license_row.status = "allocated" if license_row.status != "active" else "active"
    db.commit()
    db.refresh(license_row)
    return {"message": "License key rotated", "data": serialize_license(license_row, raw_key)}


@router.post("/dev/status")
def dev_status(payload: StatusUpdateRequest, db: Session = Depends(get_db), auth: AuthContext = Depends(require_billing_admin)):
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=404, detail="Not found")
    subscription = get_or_create_subscription(db, auth.company_id)
    subscription.status = payload.status
    if payload.status == "active":
        now = utc_now()
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=30)
    db.commit()
    db.refresh(subscription)
    return {"message": "Development billing status updated", "data": serialize_subscription(subscription)}


def serialize_invoice(invoice: BillingInvoice) -> dict:
    return {
        "id": invoice.id,
        "provider": invoice.provider,
        "provider_invoice_id": invoice.provider_invoice_id,
        "amount_cents": invoice.amount_cents,
        "currency": invoice.currency,
        "status": invoice.status,
        "invoice_url": invoice.invoice_url,
        "hosted_payment_url": invoice.hosted_payment_url,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
    }


def parse_stripe_event(body: bytes, signature_header: str | None) -> dict:
    if settings.STRIPE_WEBHOOK_SECRET:
        if not signature_header:
            raise HTTPException(status_code=400, detail="Missing Stripe signature")
        values = {}
        for part in signature_header.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                values.setdefault(key, []).append(value)
        timestamp = values.get("t", [None])[0]
        signatures = values.get("v1", [])
        if not timestamp or not signatures:
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")
        signed_payload = f"{timestamp}.{body.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, item) for item in signatures):
            raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid Stripe payload")


def from_stripe_ts(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def stripe_get(path: str, params: dict | None = None) -> dict | None:
    if not settings.STRIPE_SECRET_KEY:
        return None
    import httpx

    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            f"https://api.stripe.com/v1/{path.lstrip('/')}",
            auth=(settings.STRIPE_SECRET_KEY, ""),
            params=params or {},
        )
    if response.status_code >= 400:
        return None
    return response.json()


def store_payment_method(customer: BillingCustomer, payment_method: dict | None) -> None:
    if not payment_method:
        return
    card = payment_method.get("card") or {}
    if not card.get("last4"):
        return
    customer.provider_payment_method_id = str(payment_method.get("id") or customer.provider_payment_method_id or "")
    customer.payment_method_brand = card.get("brand")
    customer.payment_method_last4 = card.get("last4")
    customer.payment_method_exp_month = card.get("exp_month")
    customer.payment_method_exp_year = card.get("exp_year")


def sync_stripe_customer_metadata(customer: BillingCustomer, source: dict | None = None) -> None:
    if source:
        customer_details = source.get("customer_details") or {}
        customer.billing_email = customer_details.get("email") or source.get("customer_email") or customer.billing_email
    if not customer.provider_customer_id:
        return
    stripe_customer = stripe_get(
        f"customers/{customer.provider_customer_id}",
        {"expand[]": "invoice_settings.default_payment_method"},
    )
    if stripe_customer:
        customer.billing_email = stripe_customer.get("email") or customer.billing_email
        default_payment_method = (stripe_customer.get("invoice_settings") or {}).get("default_payment_method")
        if isinstance(default_payment_method, dict):
            store_payment_method(customer, default_payment_method)
            return
    payment_methods = stripe_get(
        "payment_methods",
        {"customer": customer.provider_customer_id, "type": "card", "limit": "1"},
    )
    methods = (payment_methods or {}).get("data") or []
    if methods:
        store_payment_method(customer, methods[0])


def resolve_company_from_stripe_object(db: Session, data_object: dict) -> str | None:
    metadata = data_object.get("metadata") or {}
    company_id = metadata.get("company_id") or data_object.get("client_reference_id")
    if company_id:
        return str(company_id)
    customer_id = data_object.get("customer")
    if customer_id:
        customer = db.execute(
            select(BillingCustomer).where(
                BillingCustomer.provider == "stripe",
                BillingCustomer.provider_customer_id == str(customer_id),
            )
        ).scalar_one_or_none()
        if customer:
            return customer.company_id
    subscription_id = data_object.get("subscription") or data_object.get("id")
    if subscription_id:
        subscription = db.execute(
            select(BillingSubscription).where(BillingSubscription.provider_subscription_id == str(subscription_id))
        ).scalar_one_or_none()
        if subscription:
            return subscription.company_id
    return None


def apply_stripe_event(db: Session, company_id: str, event_type: str, data_object: dict) -> None:
    if event_type == "checkout.session.completed":
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")
        plan_key = (data_object.get("metadata") or {}).get("plan_key") or "standard"
        if customer_id:
            customer = get_customer(db, company_id, "stripe")
            if not customer:
                customer = BillingCustomer(company_id=company_id, provider="stripe")
                db.add(customer)
            customer.provider_customer_id = str(customer_id)
            sync_stripe_customer_metadata(customer, data_object)
        subscription = get_or_create_subscription(db, company_id)
        subscription.provider = "stripe"
        subscription.plan_key = plan_key
        subscription.provider_subscription_id = str(subscription_id) if subscription_id else subscription.provider_subscription_id
        subscription.status = "active" if not settings.TRIAL_DAYS else "trialing"
        return

    if event_type.startswith("customer.subscription."):
        subscription = get_or_create_subscription(db, company_id)
        metadata = data_object.get("metadata") or {}
        subscription.provider = "stripe"
        subscription.provider_subscription_id = str(data_object.get("id") or subscription.provider_subscription_id)
        subscription.plan_key = metadata.get("plan_key") or subscription.plan_key
        subscription.status = data_object.get("status") or subscription.status
        subscription.trial_start = from_stripe_ts(data_object.get("trial_start")) or subscription.trial_start
        subscription.trial_end = from_stripe_ts(data_object.get("trial_end")) or subscription.trial_end
        subscription.current_period_start = from_stripe_ts(data_object.get("current_period_start")) or subscription.current_period_start
        subscription.current_period_end = from_stripe_ts(data_object.get("current_period_end")) or subscription.current_period_end
        subscription.cancel_at_period_end = bool(data_object.get("cancel_at_period_end"))
        return

    if event_type in {"invoice.payment_succeeded", "invoice.payment_failed", "invoice.finalized"}:
        customer_id = data_object.get("customer")
        if customer_id:
            customer = get_customer(db, company_id, "stripe")
            if not customer:
                customer = BillingCustomer(company_id=company_id, provider="stripe")
                db.add(customer)
            customer.provider_customer_id = str(customer_id)
            sync_stripe_customer_metadata(customer, data_object)
        provider_invoice_id = str(data_object.get("id") or "")
        invoice = db.execute(
            select(BillingInvoice).where(
                BillingInvoice.provider == "stripe",
                BillingInvoice.provider_invoice_id == provider_invoice_id,
            )
        ).scalar_one_or_none()
        if not invoice:
            invoice = BillingInvoice(company_id=company_id, provider="stripe", provider_invoice_id=provider_invoice_id)
            db.add(invoice)
        invoice.amount_cents = int(data_object.get("amount_paid") or data_object.get("amount_due") or 0)
        invoice.currency = data_object.get("currency") or settings.BILLING_CURRENCY
        invoice.status = "paid" if event_type == "invoice.payment_succeeded" else "failed" if event_type == "invoice.payment_failed" else data_object.get("status", "open")
        invoice.invoice_url = data_object.get("hosted_invoice_url") or data_object.get("invoice_pdf")
        invoice.hosted_payment_url = data_object.get("hosted_invoice_url")
        subscription = get_or_create_subscription(db, company_id)
        if event_type == "invoice.payment_succeeded":
            subscription.status = "active"
            license_row, _ = get_or_create_license(db, company_id)
            activate_license_for_period(license_row, subscription)
        if event_type == "invoice.payment_failed":
            subscription.status = "past_due"
