from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class BillingPlan:
    key: str
    name: str
    price_cents: int
    interval: str
    included_employees: int | None
    description: str


def get_plans() -> list[BillingPlan]:
    return [
        BillingPlan("free", "Free", 0, "month", 10, "Trial workspace for setup, testing, and onboarding."),
        BillingPlan(
            "standard",
            "Standard",
            settings.STANDARD_PLAN_PRICE_CENTS,
            "month",
            settings.STANDARD_PLAN_INCLUDED_LICENSES,
            "Recommended monthly workspace license for real company operations.",
        ),
    ]


class BillingProviderError(RuntimeError):
    pass


class ProviderNotConfigured(BillingProviderError):
    pass


class BillingProvider:
    key = "base"

    def create_checkout_session(self, *, company_id: str, plan_key: str, success_url: str, cancel_url: str, customer_id: str | None = None) -> dict:
        raise NotImplementedError

    def create_customer_portal_session(self, *, company_id: str, return_url: str, customer_id: str | None = None) -> dict:
        raise NotImplementedError

    def change_plan(self, *, company_id: str, plan_key: str) -> dict:
        raise NotImplementedError
