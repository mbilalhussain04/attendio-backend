from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(SERVICE_DIR / ".env", SERVICES_DIR / ".env"), case_sensitive=True, extra="ignore")
    APP_NAME: str = "Attendio Notification Service"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8003
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./notification.db"
    SECRET_KEY: str = "change-me"
    SESSION_COOKIE_NAME: str = "attendio_session"
    INTERNAL_SERVICE_TOKEN: str = "change-me-internal"
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "no-reply@attendio.local"
    SMTP_USE_TLS: bool = True

settings = Settings()
