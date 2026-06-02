from datetime import datetime, timedelta, timezone
from hashlib import sha256
from jose import jwt, JWTError
from passlib.context import CryptContext
from slugify import slugify as _slugify
import secrets

from app.core.config import settings

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
ALGORITHM = 'HS256'


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return pwd_context.verify(password, password_hash)


def generate_token(payload: dict, expires_delta: timedelta) -> str:
    to_encode = payload.copy()
    to_encode['exp'] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(to_encode, settings.JWT_ACCESS_SECRET or settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(payload: dict) -> str:
    return generate_token(payload, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(payload: dict, days: int | None = None) -> str:
    return generate_token(payload, timedelta(days=days or settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_ACCESS_SECRET or settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError('Invalid token') from exc


def token_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def random_secret(length: int = 32) -> str:
    return secrets.token_hex(length // 2)


def random_password(length: int = 14) -> str:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def slugify_name(name: str) -> str:
    return _slugify(name)
