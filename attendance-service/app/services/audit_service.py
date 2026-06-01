from sqlalchemy.orm import Session
from uuid import UUID
from app.models.attendance import AuditLog


def _coerce_uuid(value):
    if isinstance(value, UUID) or value is None:
        return value
    return UUID(str(value))


def log_audit(db: Session, company_id: str, actor_user_id: str | None, action: str, target_type: str, target_id: str | None = None, metadata: dict | None = None):
    row = AuditLog(company_id=_coerce_uuid(company_id), actor_user_id=_coerce_uuid(actor_user_id), action=action, target_type=target_type, target_id=target_id, metadata_json=metadata)
    db.add(row)
    db.flush()
    return row
