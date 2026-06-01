from app.core.config import settings
from app.providers.base import BillingProvider, ProviderNotConfigured


class StripeBillingProvider(BillingProvider):
    key = "stripe"

    def _ensure_configured(self):
        if not settings.STRIPE_SECRET_KEY:
            raise ProviderNotConfigured("Stripe is not configured. Add STRIPE_SECRET_KEY and Stripe price IDs.")

    def _price_for_plan(self, plan_key: str) -> str:
        prices = {
            "free": None,
            "standard": settings.STRIPE_PRICE_STANDARD,
        }
        price_id = prices.get(plan_key)
        if not price_id:
            raise ProviderNotConfigured(f"Stripe price is missing for plan '{plan_key}'.")
        return price_id

    def create_checkout_session(self, *, company_id: str, plan_key: str, success_url: str, cancel_url: str, customer_id: str | None = None) -> dict:
        self._ensure_configured()
        import httpx

        data = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": company_id,
            "line_items[0][price]": self._price_for_plan(plan_key),
            "line_items[0][quantity]": "1",
            "metadata[company_id]": company_id,
            "metadata[plan_key]": plan_key,
            "subscription_data[metadata][company_id]": company_id,
            "subscription_data[metadata][plan_key]": plan_key,
            "allow_promotion_codes": "true",
            "billing_address_collection": "auto",
        }
        if customer_id:
            data["customer"] = customer_id
        if settings.TRIAL_DAYS > 0:
            data["subscription_data[trial_period_days]"] = str(settings.TRIAL_DAYS)
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(settings.STRIPE_SECRET_KEY, ""),
                data=data,
            )
        if response.status_code >= 400:
            detail = response.json().get("error", {}).get("message", "Stripe checkout failed")
            raise RuntimeError(detail)
        session = response.json()
        return {"provider": self.key, "mode": "stripe", "id": session.get("id"), "url": session.get("url")}

    def create_customer_portal_session(self, *, company_id: str, return_url: str, customer_id: str | None = None) -> dict:
        self._ensure_configured()
        if not customer_id:
            raise ProviderNotConfigured("Stripe customer is not linked yet. Complete checkout first.")
        import httpx

        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://api.stripe.com/v1/billing_portal/sessions",
                auth=(settings.STRIPE_SECRET_KEY, ""),
                data={"customer": customer_id, "return_url": return_url},
            )
        if response.status_code >= 400:
            detail = response.json().get("error", {}).get("message", "Stripe portal failed")
            raise RuntimeError(detail)
        session = response.json()
        return {"provider": self.key, "mode": "stripe", "id": session.get("id"), "url": session.get("url")}

    def change_plan(self, *, company_id: str, plan_key: str) -> dict:
        self._ensure_configured()
        self._price_for_plan(plan_key)
        return {"provider": self.key, "plan_key": plan_key, "message": "Stripe plan change requires provider subscription sync."}
