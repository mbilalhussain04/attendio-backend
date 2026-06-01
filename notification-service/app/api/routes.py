from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps.auth import get_actor, require_internal
from app.services.notifications import service

router = APIRouter(prefix="/notifications")
class CreateNotificationRequest(BaseModel):
    company_id: str
    user_id: str
    kind: str
    title: str
    body: str
    metadata: dict | None = None
    template_key: str | None = None
    channels: list[str] | None = None
    preference_key: str = "security"
    preferences: dict | None = None

@router.get("/health")
def health():
    return {"status": "ok", "service": "notification-service"}

@router.get("")
def list_notifications(actor=Depends(get_actor), db: Session = Depends(get_db)):
    items = service.list_for_user(db, actor)
    return {"message": "Notifications fetched successfully", "data": [{"id": str(item.id), "kind": item.kind, "title": item.title, "body": item.body, "is_read": item.is_read, "created_at": item.created_at} for item in items]}

@router.post("/{notification_id}/read")
def mark_read(notification_id: UUID, actor=Depends(get_actor), db: Session = Depends(get_db)):
    item = service.mark_read(db, actor, notification_id)
    return {"message": "Notification marked read", "data": {"id": str(item.id)}}

@router.post("/read-all")
def read_all(actor=Depends(get_actor), db: Session = Depends(get_db)):
    return {"message": "Notifications marked read", "data": {"count": service.mark_all_read(db, actor)}}

@router.post("/internal")
def create_notification(payload: CreateNotificationRequest, _=Depends(require_internal), db: Session = Depends(get_db)):
    item = service.create(db, payload=payload.model_dump())
    return {"message": "Notification created" if item else "Notification skipped by preferences", "data": {"id": str(item.id)} if item else None}

@router.get("/deliveries")
def deliveries(scope: str = "self", actor=Depends(get_actor), db: Session = Depends(get_db)):
    items = service.list_deliveries(db, actor, scope=scope)
    return {"message": "Deliveries fetched successfully", "data": [{"id": str(item.id), "channel": item.channel, "status": item.status, "retry_count": item.retry_count, "last_error": item.last_error} for item in items]}

@router.delete("/deliveries")
def clear_deliveries(actor=Depends(get_actor), db: Session = Depends(get_db)):
    service.clear_deliveries(db, actor)
    return {"message": "Delivery history cleared", "data": {"cleared": True}}

@router.post("/internal/retry")
def retry_pending(_=Depends(require_internal), db: Session = Depends(get_db)):
    return {"message": "Retry queue processed", "data": {"count": service.retry_pending(db)}}
