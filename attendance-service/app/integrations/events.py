from __future__ import annotations
import os
from attendio_shared.events import publish_event as shared_publish_event

def publish_event(event_name: str, tenant_id: str | None, payload: dict) -> bool:
    return shared_publish_event(event_name=event_name, tenant_id=tenant_id, payload=payload, source=os.getenv('APP_NAME', 'service'))
