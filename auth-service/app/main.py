from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from prometheus_client import make_asgi_app
from starlette.middleware.sessions import SessionMiddleware

from app.api.api import api_router
from app.core.config import settings
from app.middleware.tenant import TenantMiddleware
from app.seed.bootstrap import ensure_seed_data
from app.db.session import SessionLocal
from app.services.auth import service

TAGS_METADATA = [
    {"name": "Health", "description": "Health checks and metrics."},
    {
        "name": "Authentication",
        "description": "Bootstrap company, login, refresh, me, email verification, password reset, impersonation.",
    },
    {"name": "MFA", "description": "TOTP MFA setup and verify endpoints."},
    {"name": "SSO", "description": "Google and Microsoft SSO entry and callback endpoints."},
    {"name": "Sessions", "description": "Current sessions and revocation."},
    {"name": "Roles & Permissions", "description": "Read permissions, roles, and create custom roles."},
    {
        "name": "Employees",
        "description": "Single create, bulk create, import, template download, list and detail.",
    },
    {"name": "API Keys", "description": "Issue and revoke tenant scoped API keys."},
    {"name": "Audit Logs", "description": "Tenant scoped audit trail."},
    {"name": "Kiosk", "description": "Kiosk pin and kiosk login."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_seed_data()
    async def reminder_loop():
        while True:
            with SessionLocal() as db:
                service.send_scheduled_mfa_reminders(db)
            await asyncio.sleep(60 * 60)
    task = asyncio.create_task(reminder_loop())
    yield
    task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
    lifespan=lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema["servers"] = [
        {"url": "http://localhost", "description": "Local gateway"},
    ]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.mount("/metrics", make_asgi_app())
