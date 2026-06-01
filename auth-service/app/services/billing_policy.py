import json
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

from fastapi import HTTPException

from app.core.config import settings


def _unrestricted() -> dict:
    return {
        "enabled": False,
        "mode": "unrestricted",
        "limits": {"branches": None, "projects": None, "employees": None, "downloads": None},
        "can_download": True,
        "workspace_locked": False,
    }


def get_entitlements(company_id: str) -> dict:
    if not settings.BILLING_ENABLED:
        return _unrestricted()
    endpoint = f"{settings.BILLING_SERVICE_URL.rstrip('/')}/api/v1/billing/internal/entitlements/{company_id}"
    req = urlrequest.Request(endpoint, headers={"x-internal-service-token": settings.INTERNAL_SERVICE_TOKEN})
    try:
        with urlrequest.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"Billing policy is unavailable: {exc}")
    return (payload.get("data") or {}).get("entitlements") or _unrestricted()


def assert_workspace_not_locked(company_id: str) -> dict:
    entitlements = get_entitlements(company_id)
    if entitlements.get("workspace_locked"):
        raise HTTPException(status_code=402, detail="Payment is required before this workspace can be changed.")
    return entitlements


def assert_limit_available(company_id: str, resource: str, current_count: int, adding: int = 1) -> dict:
    entitlements = assert_workspace_not_locked(company_id)
    limit = (entitlements.get("limits") or {}).get(resource)
    if limit is not None and current_count + adding > int(limit):
        raise HTTPException(
            status_code=402,
            detail=f"Free plan limit reached. Upgrade to Standard to add more {resource.replace('_', ' ')}.",
        )
    return entitlements
