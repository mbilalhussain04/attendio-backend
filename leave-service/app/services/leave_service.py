from datetime import date, datetime, timedelta
import re
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models.leave import LeaveApproval, LeaveEntitlementGrant, LeaveEntitlementPolicy, LeavePolicy, LeaveRequest, LeaveType
from app.utils.http import http_error


def _uuid(value):
    return value if isinstance(value, UUID) else UUID(str(value))


def get_policy(db: Session, company_id: str):
    row = db.query(LeavePolicy).filter(LeavePolicy.company_id == _uuid(company_id)).first()
    if not row:
        row = LeavePolicy(company_id=_uuid(company_id))
        db.add(row)
        db.flush()
    return row


def update_policy(db: Session, company_id: str, payload: dict):
    row = get_policy(db, company_id)
    for key, value in payload.items():
        if value is not None:
            setattr(row, key, value)
    db.flush()
    return row


def list_types(db: Session, company_id: str, include_inactive: bool = False):
    query = db.query(LeaveType).filter(LeaveType.company_id == _uuid(company_id))
    if not include_inactive:
        query = query.filter(LeaveType.active.is_(True))
    return query.order_by(LeaveType.name.asc()).all()


def list_entitlement_policies(db: Session, company_id: str, include_inactive: bool = False):
    query = db.query(LeaveEntitlementPolicy).options(joinedload(LeaveEntitlementPolicy.leave_type)).filter(LeaveEntitlementPolicy.company_id == _uuid(company_id))
    if not include_inactive:
        query = query.filter(LeaveEntitlementPolicy.active.is_(True))
    return query.order_by(LeaveEntitlementPolicy.priority.asc(), LeaveEntitlementPolicy.name.asc()).all()


def upsert_entitlement_policy(db: Session, company_id: str, payload: dict, policy_id: str | None = None):
    company = _uuid(company_id)
    leave_type = db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.id == payload["leave_type_id"]).first()
    if not leave_type:
        raise http_error(404, "Leave type not found")
    row = db.query(LeaveEntitlementPolicy).filter(LeaveEntitlementPolicy.company_id == company, LeaveEntitlementPolicy.id == _uuid(policy_id)).first() if policy_id else None
    if not row:
        row = LeaveEntitlementPolicy(company_id=company)
        db.add(row)
    for key, value in payload.items():
        if key in {"contract_type", "employment_type"} and isinstance(value, str):
            value = value.strip() or None
        setattr(row, key, value)
    db.flush()
    return row


def upsert_type(db: Session, company_id: str, payload: dict, type_id: str | None = None):
    company = _uuid(company_id)
    row = db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.id == _uuid(type_id)).first() if type_id else None
    code = (payload.get("code") or "").strip().lower()
    if not row and code:
        row = db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.code == code).first()
    if not row:
        row = LeaveType(company_id=company)
        db.add(row)
    if not code and not row.code:
        root = re.sub(r"[^a-z0-9]+", "-", payload["name"].strip().lower()).strip("-") or "leave"
        code = root[:72]
        suffix = 1
        while db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.code == code).first():
            suffix += 1
            code = f"{root[: max(1, 76 - len(str(suffix)))]}-{suffix}"
    if code:
        payload["code"] = code
    for key, value in payload.items():
        if value is not None:
            setattr(row, key, value)
    db.flush()
    return row


def archive_type(db: Session, company_id: str, type_id: str):
    row = db.query(LeaveType).filter(LeaveType.company_id == _uuid(company_id), LeaveType.id == _uuid(type_id)).first()
    if not row:
        raise http_error(404, "Leave type not found")
    row.active = False
    db.flush()
    return row


def _metadata(profile: dict | None):
    user = (profile or {}).get("user", profile or {})
    return {
        "contract_type": user.get("contract_type"),
        "employment_type": user.get("employment_type"),
    }


def _policy_matches(policy: LeaveEntitlementPolicy, profile: dict | None):
    metadata = _metadata(profile)
    return (not policy.contract_type or policy.contract_type == metadata["contract_type"]) and (not policy.employment_type or policy.employment_type == metadata["employment_type"])


def list_grants(db: Session, company_id: str, user_id: str | None = None, year: int | None = None):
    query = db.query(LeaveEntitlementGrant).options(joinedload(LeaveEntitlementGrant.leave_type)).filter(LeaveEntitlementGrant.company_id == _uuid(company_id))
    if user_id:
        query = query.filter(LeaveEntitlementGrant.user_id == _uuid(user_id))
    if year:
        query = query.filter(LeaveEntitlementGrant.year == year)
    return query.order_by(LeaveEntitlementGrant.year.desc(), LeaveEntitlementGrant.created_at.desc()).all()


def upsert_grant(db: Session, company_id: str, payload: dict, *, source: str = "override", policy_id: UUID | None = None, grant_id: str | None = None):
    company = _uuid(company_id)
    leave_type = db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.id == payload["leave_type_id"]).first()
    if not leave_type:
        raise http_error(404, "Leave type not found")
    row = db.query(LeaveEntitlementGrant).filter(
        LeaveEntitlementGrant.company_id == company,
        LeaveEntitlementGrant.id == _uuid(grant_id),
    ).first() if grant_id else db.query(LeaveEntitlementGrant).filter(
        LeaveEntitlementGrant.company_id == company,
        LeaveEntitlementGrant.user_id == _uuid(payload["user_id"]),
        LeaveEntitlementGrant.leave_type_id == payload["leave_type_id"],
        LeaveEntitlementGrant.year == payload["year"],
    ).first()
    if not row:
        row = LeaveEntitlementGrant(company_id=company)
        db.add(row)
    row.user_id = _uuid(payload["user_id"])
    row.leave_type_id = payload["leave_type_id"]
    row.year = payload["year"]
    row.entitlement_days = payload["entitlement_days"]
    row.employee_snapshot = payload.get("employee_snapshot")
    row.note = payload.get("note")
    row.source = source
    row.policy_id = policy_id
    db.flush()
    return row


def archive_entitlement_policy(db: Session, company_id: str, policy_id: str):
    row = db.query(LeaveEntitlementPolicy).filter(
        LeaveEntitlementPolicy.company_id == _uuid(company_id),
        LeaveEntitlementPolicy.id == _uuid(policy_id),
    ).first()
    if not row:
        raise http_error(404, "Entitlement policy not found")
    row.active = False
    db.flush()
    return row


def delete_grant(db: Session, company_id: str, grant_id: str):
    row = db.query(LeaveEntitlementGrant).filter(
        LeaveEntitlementGrant.company_id == _uuid(company_id),
        LeaveEntitlementGrant.id == _uuid(grant_id),
    ).first()
    if not row:
        raise http_error(404, "Entitlement grant not found")
    db.delete(row)
    db.flush()
    return {"id": str(row.id), "deleted": True}


def ensure_policy_grants(db: Session, company_id: str, user_id: str, year: int, profile: dict | None = None, employee_snapshot: dict | None = None):
    existing = {grant.leave_type_id for grant in list_grants(db, company_id, user_id=user_id, year=year)}
    selected = {}
    for policy in list_entitlement_policies(db, company_id):
        if policy.leave_type_id not in existing and _policy_matches(policy, profile):
            selected.setdefault(policy.leave_type_id, policy)
    created = []
    for policy in selected.values():
        created.append(upsert_grant(db, company_id, {
            "user_id": user_id,
            "leave_type_id": policy.leave_type_id,
            "year": year,
            "entitlement_days": float(policy.entitlement_days),
            "employee_snapshot": employee_snapshot,
            "note": f"Generated from {policy.name}",
        }, source="policy", policy_id=policy.id))
    return created


def work_days(from_date: date, to_date: date, count_weekends: bool, excluded_dates: set[date] | None = None):
    cursor = from_date
    days = 0
    excluded_dates = excluded_dates or set()
    while cursor <= to_date:
        if cursor not in excluded_dates and (count_weekends or cursor.weekday() < 5):
            days += 1
        cursor += timedelta(days=1)
    return days


def query_requests(db: Session, company_id: str):
    return db.query(LeaveRequest).options(joinedload(LeaveRequest.leave_type), joinedload(LeaveRequest.approvals)).filter(LeaveRequest.company_id == _uuid(company_id))


def list_requests(db: Session, company_id: str, user_id: str | None = None, year: int | None = None, status: str | None = None):
    query = query_requests(db, company_id)
    if user_id:
        query = query.filter(LeaveRequest.user_id == _uuid(user_id))
    if year:
        query = query.filter(LeaveRequest.year == year)
    if status:
        query = query.filter(LeaveRequest.status == status)
    return query.order_by(LeaveRequest.created_at.desc()).all()


def balance_rows(db: Session, company_id: str, user_id: str, year: int, profile: dict | None = None, employee_snapshot: dict | None = None):
    ensure_policy_grants(db, company_id, user_id, year, profile=profile, employee_snapshot=employee_snapshot)
    leave_types = list_types(db, company_id)
    requests = list_requests(db, company_id, user_id=user_id, year=year)
    grants = {grant.leave_type_id: grant for grant in list_grants(db, company_id, user_id=user_id, year=year)}
    rows = []
    for item in leave_types:
        taken = sum(float(request.total_days) for request in requests if request.leave_type_id == item.id and request.status == "approved")
        pending = sum(float(request.total_days) for request in requests if request.leave_type_id == item.id and request.status == "pending")
        entitlement = float(grants[item.id].entitlement_days) if item.id in grants else float(item.entitlement_days) if item.entitlement_days is not None else None
        rows.append({
            "leave_type_id": item.id,
            "code": item.code,
            "name": item.name,
            "paid": item.paid,
            "entitlement_days": entitlement,
            "taken_days": taken,
            "pending_days": pending,
            "available_days": None if entitlement is None else entitlement - taken - pending,
        })
    return rows


def create_request(db: Session, company_id: str, user_id: str, payload: dict, employee_snapshot: dict | None = None, excluded_dates: set[date] | None = None):
    company = _uuid(company_id)
    leave_type = db.query(LeaveType).filter(LeaveType.company_id == company, LeaveType.id == payload["leave_type_id"], LeaveType.active.is_(True)).first()
    if not leave_type:
        raise http_error(404, "Leave type not found")
    if payload["from_date"].year != payload["to_date"].year:
        raise http_error(400, "Leave requests must stay within one calendar year")
    policy = get_policy(db, company_id)
    total = 0.5 if payload["session"] == "half_day" else float(work_days(payload["from_date"], payload["to_date"], policy.count_weekends, excluded_dates))
    if total <= 0:
        raise http_error(400, "Selected dates do not contain requestable working days")
    overlap = query_requests(db, company_id).filter(
        LeaveRequest.user_id == _uuid(user_id),
        LeaveRequest.status.in_(["pending", "approved"]),
        LeaveRequest.from_date <= payload["to_date"],
        LeaveRequest.to_date >= payload["from_date"],
    ).first()
    if overlap:
        raise http_error(409, "Leave request overlaps an existing request")
    available = next((row["available_days"] for row in balance_rows(db, company_id, user_id, payload["from_date"].year, profile=employee_snapshot, employee_snapshot=employee_snapshot) if row["leave_type_id"] == leave_type.id), None)
    if not policy.allow_negative_balance and available is not None and total > available:
        raise http_error(409, "Leave request exceeds available balance")
    row = LeaveRequest(company_id=company, user_id=_uuid(user_id), employee_snapshot=employee_snapshot, total_days=total, year=payload["from_date"].year, **payload)
    db.add(row)
    db.flush()
    for level in range(1, policy.approval_levels + 1):
        row.approvals.append(LeaveApproval(company_id=company, level=level))
    db.flush()
    return row


def cancel_request(db: Session, company_id: str, user_id: str, request_id: str):
    row = query_requests(db, company_id).filter(LeaveRequest.id == _uuid(request_id), LeaveRequest.user_id == _uuid(user_id)).first()
    if not row:
        raise http_error(404, "Leave request not found")
    if row.status != "pending":
        raise http_error(409, "Only pending leave requests can be cancelled")
    row.status = "cancelled"
    db.flush()
    return row


def review_request(db: Session, company_id: str, reviewer_user_id: str, request_id: str, status: str, note: str | None):
    row = query_requests(db, company_id).filter(LeaveRequest.id == _uuid(request_id)).first()
    if not row:
        raise http_error(404, "Leave request not found")
    if row.status != "pending":
        raise http_error(409, "Leave request is already decided")
    now = datetime.utcnow()
    pending = sorted((approval for approval in row.approvals if approval.status == "pending"), key=lambda approval: approval.level)
    approval = pending[0] if pending else None
    if approval:
        approval.status = status
        approval.note = note
        approval.reviewer_user_id = _uuid(reviewer_user_id)
        approval.decided_at = now
    if status == "rejected":
        row.status = "rejected"
    elif not any(approval.status == "pending" for approval in row.approvals):
        row.status = "approved"
    row.decided_by_user_id = _uuid(reviewer_user_id)
    row.decision_note = note
    row.decided_at = now
    db.flush()
    return row
