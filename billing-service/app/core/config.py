from pathlib import Path
import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent
ENV_FILES = (
    SERVICES_DIR / ".env",
    SERVICE_DIR / ".env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    APP_NAME: str = "Attendio Billing Service"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8005
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/attendio_billing"
    BILLING_APP_PORT: int | None = None
    BILLING_DATABASE_URL: str | None = None
    BILLING_ENABLED: bool = False
    BILLING_PROVIDER: str = "manual"
    TRIAL_DAYS: int = 60
    BILLING_CURRENCY: str = "eur"
    STANDARD_PLAN_PRICE_CENTS: int = 3000
    STANDARD_PLAN_INCLUDED_LICENSES: int = 25
    PAYMENT_GRACE_DAYS: int = 7
    BILLING_SUCCESS_URL: str = "http://localhost:5173/settings?tab=billing&billing=success"
    BILLING_CANCEL_URL: str = "http://localhost:5173/settings?tab=billing&billing=cancelled"

    JWT_ACCESS_SECRET: str = "change-me"
    INTERNAL_SERVICE_TOKEN: str = "change-me-internal"
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    SESSION_COOKIE_NAME: str = "attendio_session"
    BASE_DOMAIN: str = "lvh.me"
    CORS_ORIGINS: list[str] | str = []

    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_STANDARD: str | None = None

    PAYONEER_CLIENT_ID: str | None = None
    PAYONEER_CLIENT_SECRET: str | None = None
    PAYONEER_WEBHOOK_SECRET: str | None = None

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod", "false", "0", "no"}:
                return False
            if normalized in {"development", "dev", "true", "1", "yes"}:
                return True
        return value

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value or []

    @model_validator(mode="after")
    def apply_root_aliases(self):
        if self.BILLING_APP_PORT is not None:
            self.APP_PORT = self.BILLING_APP_PORT
        if self.BILLING_DATABASE_URL and "DATABASE_URL" not in os.environ:
            self.DATABASE_URL = self.BILLING_DATABASE_URL
        for key in (
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PRICE_STANDARD",
            "PAYONEER_CLIENT_ID",
            "PAYONEER_CLIENT_SECRET",
            "PAYONEER_WEBHOOK_SECRET",
        ):
            value = getattr(self, key)
            if isinstance(value, str) and not value.strip():
                setattr(self, key, None)
        self.BILLING_PROVIDER = (self.BILLING_PROVIDER or "manual").strip().lower()
        return self


settings = Settings()
