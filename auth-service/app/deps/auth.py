from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.models.company import Company
from app.models.role import Role
from app.services.auth import service

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)):
    token = None
    if credentials:
        token = credentials.credentials
    else:
        token = (
            request.cookies.get(settings.SESSION_COOKIE_NAME)
            or request.cookies.get('attendio_session')
            or request.cookies.get('access_token')
        )
    if not token:
        raise HTTPException(status_code=401, detail='Authentication required')
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail='Invalid token')
    request.state.token_payload = payload

    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
        .where(User.id == payload.get('sub'))
    )
    user = db.execute(stmt).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail='User not found')
    tenant = getattr(request.state, 'tenant', None)
    if tenant and str(user.company_id) != str(tenant.id):
        raise HTTPException(status_code=403, detail='Cross tenant access denied')
    return user


def require_permissions(*required: str):
    def dependency(user=Depends(get_current_user), db: Session = Depends(get_db)):
        permissions = set(service.permission_keys_for_user(db, user))
        if not any(item in permissions for item in required):
            raise HTTPException(status_code=403, detail='Insufficient permissions')
        return user
    return dependency
