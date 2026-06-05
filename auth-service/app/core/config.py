from pathlib import Path
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent
ENV_FILES = (
    SERVICES_DIR / '.env',
    SERVICE_DIR / '.env',
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, case_sensitive=True, extra='ignore')

    APP_NAME: str = 'Attendio Auth Service'
    APP_ENV: str = 'development'
    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8000
    API_V1_PREFIX: str = '/api/v1'
    SECRET_KEY: str = 'change-me'
    JWT_ACCESS_SECRET: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    COOKIE_SECURE: bool = False
    COOKIE_DOMAIN: str | None = None
    SESSION_COOKIE_NAME: str = 'attendio_session'
    REFRESH_COOKIE_NAME: str = 'attendio_refresh'
    DEFAULT_ROOT_DOMAIN: str = 'lvh.me'
    AUTH_BASE_DOMAIN: str = 'auth.lvh.me'
    FRONTEND_BASE_URL: str = 'http://localhost:5173'
    FRONTEND_AFTER_LOGIN: str = '/dashboard'
    FRONTEND_SSO_ERROR: str = '/sign-in'
    ALLOW_EMAIL_LOGIN_FALLBACK: bool = True
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    DATABASE_URL: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/attendio_auth'
    REDIS_URL: str = 'redis://localhost:6379/0'
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    MICROSOFT_CLIENT_ID: str | None = None
    MICROSOFT_CLIENT_SECRET: str | None = None
    MICROSOFT_TENANT_ID: str | None = None
    MICROSOFT_AUTHORITY: str = 'common'
    SAML_METADATA_URL: str | None = None
    SAML_ENTITY_ID: str | None = None
    SAML_CERTIFICATE: str | None = None
    OAUTH_REDIRECT_URI: str = 'http://auth.lvh.me/api/v1/auth/sso/callback'
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = 'no-reply@attendio.local'
    SMTP_USE_TLS: bool = True
    NOTIFICATION_SERVICE_URL: str = 'http://localhost:8003'
    BILLING_SERVICE_URL: str = 'http://localhost:8005'
    BILLING_ENABLED: bool = False
    INTERNAL_SERVICE_TOKEN: str = 'change-me-internal'
    SSO_AUTO_PROVISION: bool = False
    SSO_DEFAULT_ROLE: str = 'employee'
    AUTH_APP_PORT: int | None = None
    AUTH_DATABASE_URL: str | None = None
    AZURE_CLIENT_ID: str | None = None
    AZURE_CLIENT_SECRET: str | None = None
    AZURE_TENANT_ID: str | None = None

    @model_validator(mode='after')
    def apply_root_env_aliases(self):
        if self.AUTH_APP_PORT is not None:
            self.APP_PORT = self.AUTH_APP_PORT
        if self.AUTH_DATABASE_URL and 'DATABASE_URL' not in os.environ:
            self.DATABASE_URL = self.AUTH_DATABASE_URL
        if not self.MICROSOFT_CLIENT_ID and self.AZURE_CLIENT_ID:
            self.MICROSOFT_CLIENT_ID = self.AZURE_CLIENT_ID
        if not self.MICROSOFT_CLIENT_SECRET and self.AZURE_CLIENT_SECRET:
            self.MICROSOFT_CLIENT_SECRET = self.AZURE_CLIENT_SECRET
        if not self.MICROSOFT_TENANT_ID and self.AZURE_TENANT_ID:
            self.MICROSOFT_TENANT_ID = self.AZURE_TENANT_ID
        if isinstance(self.JWT_ACCESS_SECRET, str) and not self.JWT_ACCESS_SECRET.strip():
            self.JWT_ACCESS_SECRET = None
        for key in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET', 'MICROSOFT_TENANT_ID', 'MICROSOFT_AUTHORITY'):
            value = getattr(self, key)
            if isinstance(value, str) and not value.strip():
                setattr(self, key, None)
        return self

settings = Settings()
