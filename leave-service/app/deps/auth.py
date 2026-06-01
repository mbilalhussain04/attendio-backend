from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.deps.db import get_db
from app.utils.http import http_error


@dataclass
class AuthContext:
    user_id: str
    company_id: str
    company_slug: str | None = None
    role_key: str | None = None
    permissions: list[str] = field(default_factory=list)
    email: str | None = None
    profile: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    for key in [settings.ACCESS_TOKEN_COOKIE_NAME, "attendio_session", "accessToken", "access_token"]:
        if request.cookies.get(key):
            return request.cookies.get(key)
    return None


def _host_slug(request: Request) -> str | None:
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
    suffix = "." + settings.BASE_DOMAIN.lower()
    if host.endswith(suffix):
        value = host[: -len(suffix)]
        return value if value and value not in {"www", "api", "auth"} else None
    return None


async def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    token = _extract_token(request)
    if not token:
        raise http_error(401, "Authentication required")
    try:
        payload = jwt.decode(token, settings.JWT_ACCESS_SECRET, algorithms=["HS256"])
    except JWTError:
        raise http_error(401, "Invalid or expired token")
    company_id = payload.get("companyId") or payload.get("company_id")
    if not company_id:
        raise http_error(400, "Company context missing in token")
    ctx = AuthContext(
        user_id=str(payload.get("sub") or payload.get("userId") or payload.get("id")),
        company_id=str(company_id),
        company_slug=payload.get("companySlug") or payload.get("company_slug"),
        role_key=payload.get("roleKey") or payload.get("role_key"),
        permissions=[str(item) for item in payload.get("permissions", [])],
        email=payload.get("email"),
        raw=payload,
    )
    slug = _host_slug(request)
    if slug and ctx.company_slug and slug != ctx.company_slug:
        raise http_error(403, "Tenant mismatch. Access to another tenant is not allowed")
    if settings.AUTH_SERVICE_URL:
        try:
            headers = {"x-internal-service-key": settings.LEAVE_SERVICE_API_KEY or ""}
            if request.headers.get("cookie"):
                headers["cookie"] = request.headers["cookie"]
            async with httpx.AsyncClient(timeout=3) as client:
                result = await client.get(f"{settings.AUTH_SERVICE_URL}/api/v1/auth/me", headers=headers)
                if result.is_success:
                    ctx.profile = result.json().get("data", result.json())
        except Exception:
            pass
    return ctx


def require_permissions(*permissions: str):
    async def dependency(auth: AuthContext = Depends(get_auth_context)):
        if any(permission not in auth.permissions for permission in permissions):
            raise http_error(403, "Missing required permission")
        return auth
    return dependency
