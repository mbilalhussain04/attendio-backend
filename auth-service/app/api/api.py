from fastapi import APIRouter
from app.api.routes import health, auth, employees, admin, kiosk, scheduling

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(employees.router)
api_router.include_router(kiosk.router)
api_router.include_router(scheduling.router)
