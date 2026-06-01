from app.providers.base import BillingProvider


class ManualBillingProvider(BillingProvider):
    key = "manual"

    def create_checkout_session(self, *, company_id: str, plan_key: str, success_url: str, cancel_url: str, customer_id: str | None = None) -> dict:
        return {
            "provider": self.key,
            "mode": "manual",
            "url": None,
            "message": "Manual billing mode is active. Add a real provider key to enable hosted payment.",
        }

    def create_customer_portal_session(self, *, company_id: str, return_url: str, customer_id: str | None = None) -> dict:
        return {
            "provider": self.key,
            "mode": "manual",
            "url": None,
            "message": "Manual billing mode is active. No external customer portal is configured.",
        }

    def change_plan(self, *, company_id: str, plan_key: str) -> dict:
        return {"provider": self.key, "plan_key": plan_key, "message": "Plan changed locally in manual billing mode."}
