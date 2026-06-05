from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator


SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent
ENV_FILES = (
    SERVICES_DIR / '.env',
    SERVICE_DIR / '.env',
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra='ignore')

    APP_NAME: str = 'Attendio Attendance Service'
    APP_ENV: str = 'development'
    APP_HOST: str = '0.0.0.0'
    APP_PORT: int = 8001
    DEBUG: bool = True

    DATABASE_URL: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/attendio_attendance'
    JWT_ACCESS_SECRET: str = 'change-me'
    ACCESS_TOKEN_COOKIE_NAME: str = 'access_token'
    AUTH_SERVICE_URL: str | None = None
    ATTENDANCE_SERVICE_API_KEY: str | None = None
    BASE_DOMAIN: str = 'lvh.me'
    CORS_ORIGINS: list[str] | str = []
    DEFAULT_TIMEZONE: str = 'Europe/Berlin'
    ATTENDANCE_APP_PORT: int | None = None
    ATTENDANCE_DATABASE_URL: str | None = None

    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(',') if item.strip()]
        return v or []

    @model_validator(mode='after')
    def apply_root_env_aliases(self):
        if self.ATTENDANCE_APP_PORT is not None:
            self.APP_PORT = self.ATTENDANCE_APP_PORT
        if self.ATTENDANCE_DATABASE_URL and 'DATABASE_URL' not in os.environ:
            self.DATABASE_URL = self.ATTENDANCE_DATABASE_URL
        return self


settings = Settings()
