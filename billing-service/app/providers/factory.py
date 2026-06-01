from app.core.config import settings
from app.providers.base import BillingProvider
from app.providers.manual import ManualBillingProvider
from app.providers.payoneer import PayoneerBillingProvider
from app.providers.stripe import StripeBillingProvider


def get_provider() -> BillingProvider:
    if settings.BILLING_PROVIDER == "stripe":
        return StripeBillingProvider()
    if settings.BILLING_PROVIDER == "payoneer":
        return PayoneerBillingProvider()
    return ManualBillingProvider()
