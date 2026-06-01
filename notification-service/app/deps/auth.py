from fastapi import Header, HTTPException, Request
from app.core.config import settings
from app.core.security import decode_token

def get_actor(request: Request) -> dict:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME) or request.cookies.get("attendio_session")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

def require_internal(x_internal_token: str | None = Header(default=None)):
    if x_internal_token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=403, detail="Internal access denied")
