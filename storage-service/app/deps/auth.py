from fastapi import HTTPException, Request
from app.core.config import settings
from app.core.security import decode_token


def get_actor(request: Request) -> dict:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME) or request.cookies.get("attendio_session") or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not payload.get("sub") or not payload.get("company_id"):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload
