from starlette.middleware.base import BaseHTTPMiddleware
from app.db.session import SessionLocal
from app.models.company import Company


def strip_port(host: str | None) -> str | None:
    return host.split(':')[0].lower() if host else None


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        candidates = []
        for key in ['host', 'x-forwarded-host']:
            value = strip_port(request.headers.get(key))
            if value and value not in candidates:
                candidates.append(value)
        for cookie_key in ['tenant_host']:
            value = strip_port(request.cookies.get(cookie_key))
            if value and value not in candidates:
                candidates.append(value)
        tenant_slug = request.cookies.get('tenant_slug')

        db = SessionLocal()
        try:
            tenant = None
            for host in candidates:
                if host in {'localhost', '127.0.0.1'}:
                    continue
                tenant = db.query(Company).filter(Company.domain == host, Company.status == 'active').first()
                if tenant:
                    break
                parts = host.split('.')
                if len(parts) >= 3:
                    slug = parts[0]
                    tenant = db.query(Company).filter(Company.slug == slug, Company.status == 'active').first()
                    if tenant:
                        break
            if not tenant and tenant_slug:
                tenant = db.query(Company).filter(Company.slug == tenant_slug, Company.status == 'active').first()
            request.state.tenant = tenant
        finally:
            db.close()
        return await call_next(request)
