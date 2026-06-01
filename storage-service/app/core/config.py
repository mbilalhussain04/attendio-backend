from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_DIR = Path(__file__).resolve().parents[2]
SERVICES_DIR = SERVICE_DIR.parent
ENV_FILES = (
    SERVICES_DIR / ".env",
    SERVICE_DIR / ".env",
    SERVICES_DIR / ".env.local",
    SERVICE_DIR / ".env.local",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, case_sensitive=True, extra="ignore")

    APP_NAME: str = "Attendio Storage Service"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8002
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./storage.db"
    SECRET_KEY: str = "change-me"
    SESSION_COOKIE_NAME: str = "attendio_session"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "attendio-files"
    STORAGE_BACKEND: str = "auto"
    LOCAL_STORAGE_DIR: str = "./.local-storage"
    PUBLIC_STORAGE_BASE_URL: str = "http://localhost:8090/api/v1/storage/files"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024


settings = Settings()
