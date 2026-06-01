from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


def log_audit(db: Session, *, company_id, actor_user_id, action, entity_type, entity_id=None, ip_address=None, user_agent=None, payload=None):
    entry = AuditLog(
        company_id=company_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        ip_address=ip_address,
        user_agent=user_agent,
        payload=payload or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
