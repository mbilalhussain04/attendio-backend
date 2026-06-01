from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.notification import Notification
from app.models.delivery import NotificationDelivery
from app.models.delivery_view import NotificationDeliveryView
from app.services.email import render, send_email

class NotificationService:
    def create(self, db: Session, *, payload: dict):
        preferences = payload.get("preferences") or {}
        requested_channels = payload.get("channels") or ["in_app"]
        preference_key = payload.get("preference_key", "security")
        channels = requested_channels if preferences.get(preference_key, True) else []
        if not channels:
            return None
        item = Notification(company_id=UUID(payload["company_id"]), user_id=UUID(payload["user_id"]), kind=payload["kind"], title=payload["title"], body=payload["body"], metadata_json=payload.get("metadata") or {})
        db.add(item); db.flush()
        for channel in channels:
            db.add(NotificationDelivery(notification_id=item.id, channel=channel, status="delivered" if channel == "in_app" else "pending", delivered_at=datetime.now(timezone.utc) if channel == "in_app" else None))
        db.commit(); db.refresh(item)
        if any(channel != "in_app" for channel in channels):
            self.retry_pending(db)
        return item
    def list_for_user(self, db: Session, actor: dict):
        return db.execute(select(Notification).where(Notification.user_id == UUID(actor["sub"])).order_by(Notification.created_at.desc()).limit(50)).scalars().all()
    def mark_read(self, db: Session, actor: dict, notification_id: UUID):
        item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == UUID(actor["sub"])))
        if not item:
            raise HTTPException(status_code=404, detail="Notification not found")
        item.is_read = True; item.read_at = datetime.now(timezone.utc); db.add(item); db.commit(); return item
    def list_deliveries(self, db: Session, actor: dict, *, scope: str = "self"):
        user_id = UUID(actor["sub"])
        cleared_at = db.scalar(select(NotificationDeliveryView.cleared_at).where(NotificationDeliveryView.user_id == user_id))
        can_view_company = scope == "company" and "settings.tenant" in (actor.get("permissions") or [])
        filters = [Notification.company_id == UUID(actor["company_id"])] if can_view_company else [Notification.user_id == user_id]
        if cleared_at:
            filters.append(NotificationDelivery.created_at > cleared_at)
        return db.execute(select(NotificationDelivery).join(Notification).where(*filters).order_by(NotificationDelivery.created_at.desc()).limit(100)).scalars().all()
    def clear_deliveries(self, db: Session, actor: dict):
        user_id = UUID(actor["sub"])
        item = db.get(NotificationDeliveryView, user_id)
        if item:
            item.cleared_at = datetime.now(timezone.utc)
        else:
            item = NotificationDeliveryView(user_id=user_id, cleared_at=datetime.now(timezone.utc))
        db.add(item); db.commit(); return item
    def retry_pending(self, db: Session):
        items = db.execute(select(NotificationDelivery).where(NotificationDelivery.status.in_(["pending", "failed"]), NotificationDelivery.retry_count < 5)).scalars().all()
        for item in items:
            item.retry_count += 1
            notification = db.scalar(select(Notification).where(Notification.id == item.notification_id))
            if item.channel == "email":
                try:
                    subject, body, html_body = render({**(notification.metadata_json or {}), "title": notification.title, "body": notification.body})
                    to_email = (notification.metadata_json or {}).get("email")
                    send_email(to_email=to_email, subject=subject, text_body=body, html_body=html_body)
                    item.status = "delivered"; item.delivered_at = datetime.now(timezone.utc); item.last_error = None
                except Exception as exc:
                    item.status = "failed"; item.last_error = str(exc)
            elif item.channel in {"sms", "push"}:
                item.status = "pending"
            db.add(item)
        db.commit()
        return len(items)
    def mark_all_read(self, db: Session, actor: dict):
        items = db.execute(select(Notification).where(Notification.user_id == UUID(actor["sub"]), Notification.is_read.is_(False))).scalars().all()
        for item in items:
            item.is_read = True; item.read_at = datetime.now(timezone.utc); db.add(item)
        db.commit(); return len(items)

service = NotificationService()
