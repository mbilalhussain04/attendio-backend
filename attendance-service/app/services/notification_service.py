from sqlalchemy.orm import Session
from uuid import UUID
from app.models.attendance import NotificationEvent


def _coerce_uuid(value):
    if isinstance(value, UUID) or value is None:
        return value
    return UUID(str(value))


def queue_notification(db: Session, company_id: str, type: str, payload: dict, user_id: str | None = None, channel: str = 'email'):
    row = NotificationEvent(company_id=_coerce_uuid(company_id), user_id=_coerce_uuid(user_id), type=type, channel=channel, payload=payload, status='queued')
    db.add(row)
    db.flush()
    return row
