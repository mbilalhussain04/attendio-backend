from datetime import datetime, date
from uuid import UUID
from typing import Any
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    success: bool = True
    message: str


class StandardResponse(BaseModel):
    success: bool = True
    data: Any


class AuditLogOut(ORMBase):
    id: UUID
    company_id: UUID
    actor_user_id: UUID | None = None
    action: str
    target_type: str
    target_id: str | None = None
    metadata_json: dict | None = None
    created_at: datetime
