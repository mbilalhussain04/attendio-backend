from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy import inspect
from sqlalchemy import text

from app.api.v1.billing import router as billing_router
from app.core.config import settings
from app.db.session import Base, engine
import app.models.billing  # noqa: F401 - register SQLAlchemy models before create_all.


def ensure_billing_schema():
    inspector = inspect(engine)
    if "billing_customers" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("billing_customers")}
    customer_columns = {
        "billing_email": "VARCHAR(255)",
        "provider_payment_method_id": "VARCHAR(255)",
        "payment_method_brand": "VARCHAR(40)",
        "payment_method_last4": "VARCHAR(8)",
        "payment_method_exp_month": "INTEGER",
        "payment_method_exp_year": "INTEGER",
    }
    with engine.begin() as conn:
        for name, ddl_type in customer_columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE billing_customers ADD COLUMN {name} {ddl_type}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_billing_schema()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
    swagger_ui_parameters={"persistAuthorization": True},
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema["servers"] = [{"url": "http://localhost", "description": "Local gateway"}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "billing_enabled": settings.BILLING_ENABLED,
        "provider": settings.BILLING_PROVIDER,
    }


app.include_router(billing_router)
