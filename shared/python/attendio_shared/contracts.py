from __future__ import annotations
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Any

class EventEnvelope(BaseModel):
    event_name: str
    source: str
    tenant_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
