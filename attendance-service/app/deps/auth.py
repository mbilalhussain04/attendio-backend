from dataclasses import dataclass, field
from typing import Any
import httpx
from jose import jwt, JWTError
from fastapi import Depends, Request
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
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    email: str | None = None
    profile: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get('authorization', '')
    if auth_header.lower().startswith('bearer '):
        return auth_header.split(' ', 1)[1].strip()
    for key in [settings.ACCESS_TOKEN_COOKIE_NAME, 'attendio_session', 'accessToken', 'access_token']:
        if request.cookies.get(key):
            return request.cookies.get(key)
    return None


def _resolve_host_slug(request: Request) -> str | None:
    host = request.headers.get('x-forwarded-host') or request.headers.get('host') or ''
    host = host.split(':')[0].strip().lower()
    if not host:
        return None
    base = settings.BASE_DOMAIN.lower()
    if host.endswith('.' + base):
        sub = host[: -(len(base) + 1)]
        return sub if sub and sub not in {'www', 'api', 'auth'} else None
    return None


async def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    token = _extract_token(request)
    if not token:
        raise http_error(401, 'Authentication required')
    try:
        payload = jwt.decode(token, settings.JWT_ACCESS_SECRET, algorithms=['HS256'])
    except JWTError:
        raise http_error(401, 'Invalid or expired token')

    company_id = payload.get('companyId') or payload.get('company_id')
    if not company_id:
        raise http_error(400, 'Company context missing in token')

    ctx = AuthContext(
        user_id=str(payload.get('sub') or payload.get('userId') or payload.get('id')),
        company_id=str(company_id),
        company_slug=payload.get('companySlug') or payload.get('company_slug'),
        role_key=payload.get('roleKey') or payload.get('role_key'),
        roles=[str(v) for v in payload.get('roles', [])],
        permissions=[str(v) for v in payload.get('permissions', [])],
        email=payload.get('email'),
        raw=payload,
    )

    host_slug = _resolve_host_slug(request)
    if host_slug and ctx.company_slug and host_slug != ctx.company_slug:
        raise http_error(403, 'Tenant mismatch. Access to another tenant is not allowed')

    if settings.AUTH_SERVICE_URL:
        try:
            headers = {'x-internal-service-key': settings.ATTENDANCE_SERVICE_API_KEY or ''}
            if request.headers.get('cookie'):
                headers['cookie'] = request.headers['cookie']
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{settings.AUTH_SERVICE_URL}/api/v1/auth/me", headers=headers)
                if res.is_success:
                    body = res.json()
                    data = body.get('data', body)
                    ctx.profile = data.get('user', data) if isinstance(data, dict) else None
        except Exception:
            pass

    return ctx


def require_permissions(*required: str):
    async def dependency(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        missing = [perm for perm in required if perm not in auth.permissions]
        if missing:
            raise http_error(403, 'Missing required permission')
        return auth
    return dependency
