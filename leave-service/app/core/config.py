from pathlib import Path
import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent
ENV_FILES = (SERVICES_DIR / ".env", SERVICE_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore")

    APP_NAME: str = "Attendio Leave Service"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8004
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/attendio_leave"
    JWT_ACCESS_SECRET: str = "change-me"
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    AUTH_SERVICE_URL: str | None = None
    ATTENDANCE_SERVICE_URL: str | None = None
    LEAVE_SERVICE_API_KEY: str | None = None
    BASE_DOMAIN: str = "lvh.me"
    CORS_ORIGINS: list[str] | str = []
    LEAVE_APP_PORT: int | None = None
    LEAVE_DATABASE_URL: str | None = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value or []

    @model_validator(mode="after")
    def apply_root_aliases(self):
        if self.LEAVE_APP_PORT is not None:
            self.APP_PORT = self.LEAVE_APP_PORT
        if self.LEAVE_DATABASE_URL and "DATABASE_URL" not in os.environ:
            self.DATABASE_URL = self.LEAVE_DATABASE_URL
        return self


settings = Settings()
