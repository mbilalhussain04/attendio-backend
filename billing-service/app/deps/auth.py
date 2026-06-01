from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db


@dataclass
class AuthContext:
    user_id: str
    company_id: str
    company_slug: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    email: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    for key in [settings.SESSION_COOKIE_NAME, settings.ACCESS_TOKEN_COOKIE_NAME, "attendio_session", "access_token"]:
        token = request.cookies.get(key)
        if token:
            return token
    return None


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(token, settings.JWT_ACCESS_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    company_id = payload.get("companyId") or payload.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="Company context missing in token")

    return AuthContext(
        user_id=str(payload.get("sub") or payload.get("userId") or payload.get("id")),
        company_id=str(company_id),
        company_slug=payload.get("companySlug") or payload.get("company_slug"),
        roles=[str(item) for item in payload.get("roles", [])],
        permissions=[str(item) for item in payload.get("permissions", [])],
        email=payload.get("email"),
        raw=payload,
    )


def require_billing_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    allowed_permissions = {"settings.tenant", "billing.manage", "reports.company"}
    allowed_roles = {"owner", "company_owner", "admin", "super_admin"}
    if allowed_permissions.intersection(auth.permissions) or allowed_roles.intersection(auth.roles):
        return auth
    raise HTTPException(status_code=403, detail="Billing is available only to company owners and admins")
