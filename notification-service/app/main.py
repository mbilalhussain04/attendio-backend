from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import settings
from app.integrations.consumer import start_consumer
from app.db.session import SessionLocal
from app.services.notifications import service

@asynccontextmanager
async def lifespan(app):
    start_consumer()
    async def retry_loop():
        while True:
            with SessionLocal() as db:
                service.retry_pending(db)
            await asyncio.sleep(60)
    task = asyncio.create_task(retry_loop())
    yield
    task.cancel()

app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(router, prefix=settings.API_V1_PREFIX)
