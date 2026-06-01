from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.auth import KioskPinRequest, KioskLoginRequest
from app.services.auth import service
from app.core.config import settings
from app.models.company import Company

router = APIRouter(prefix='/kiosk')


def req_meta(request: Request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, company):
    opts = {'httponly': True, 'samesite': 'lax', 'secure': settings.COOKIE_SECURE, 'path': '/'}
    response.set_cookie(settings.SESSION_COOKIE_NAME, access_token, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **opts)
    response.set_cookie(settings.REFRESH_COOKIE_NAME, refresh_token, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_slug', company.slug, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)
    response.set_cookie('tenant_host', company.domain, max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600, **opts)


@router.post('/pin', tags=['Kiosk'])
def set_kiosk_pin(payload: KioskPinRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.reset_pin', 'settings.kiosk'))):
    service.set_kiosk_pin(db, actor=user, target_user_id=payload.user_id, pin=payload.pin, request_meta=req_meta(request))
    return {'message': 'Kiosk PIN set successfully'}


@router.post('/login', tags=['Kiosk'])
def kiosk_login(payload: KioskLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    tenant = getattr(request.state, 'tenant', None)
    if not tenant and payload.tenant_slug:
        tenant = db.query(Company).filter(Company.slug == payload.tenant_slug, Company.status == 'active').first()
    data = service.kiosk_login(db, actor_tenant=tenant, employee_code=payload.employee_code, pin=payload.pin, request_meta=req_meta(request))
    set_auth_cookies(response, data['access_token'], data['refresh_token'], data['company'])
    return {'message': f'Kiosk login successful. Welcome, {data["user"].first_name} {data["user"].last_name}', 'data': {'user': {'id': str(data['user'].id), 'first_name': data['user'].first_name, 'last_name': data['user'].last_name, 'employee_code': data['user'].employee_code, 'is_kiosk': True}, 'redirect_url': data['redirect_url'], 'tenant_isolation': 'enabled'}}
