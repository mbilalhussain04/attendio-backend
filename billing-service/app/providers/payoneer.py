from app.core.config import settings
from app.providers.base import BillingProvider, ProviderNotConfigured


class PayoneerBillingProvider(BillingProvider):
    key = "payoneer"

    def _ensure_configured(self):
        if not settings.PAYONEER_CLIENT_ID or not settings.PAYONEER_CLIENT_SECRET:
            raise ProviderNotConfigured("Payoneer is not configured. Add Payoneer merchant API credentials.")

    def create_checkout_session(self, *, company_id: str, plan_key: str, success_url: str, cancel_url: str, customer_id: str | None = None) -> dict:
        self._ensure_configured()
        return {
            "provider": self.key,
            "mode": "payoneer",
            "url": None,
            "message": "Payoneer adapter is reserved. Wire merchant checkout API once credentials and product capability are confirmed.",
        }

    def create_customer_portal_session(self, *, company_id: str, return_url: str, customer_id: str | None = None) -> dict:
        self._ensure_configured()
        return {"provider": self.key, "mode": "payoneer", "url": return_url}

    def change_plan(self, *, company_id: str, plan_key: str) -> dict:
        self._ensure_configured()
        return {"provider": self.key, "plan_key": plan_key}
