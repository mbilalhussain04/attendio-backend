from __future__ import annotations
import json
import os
from urllib import request

try:
    from attendio_shared.events import publish_event as shared_publish_event
except ImportError:  # Local unit tests may run without the shared package on PYTHONPATH.
    shared_publish_event = None

def publish_event(event_name: str, tenant_id: str | None, payload: dict) -> bool:
    if shared_publish_event is not None:
        accepted = shared_publish_event(event_name=event_name, tenant_id=tenant_id, payload=payload, source=os.getenv('APP_NAME', 'service'))
        if accepted:
            return True
    return _publish_notification_fallback(event_name, tenant_id, payload)


def _publish_notification_fallback(event_name: str, tenant_id: str | None, payload: dict) -> bool:
    if event_name != 'notification.requested' or not tenant_id:
        return False
    base_url = os.getenv('NOTIFICATION_SERVICE_URL', 'http://localhost:8003')
    token = os.getenv('INTERNAL_SERVICE_TOKEN', 'change-me-internal')
    req = request.Request(
        f"{base_url.rstrip('/')}/api/v1/notifications/internal",
        data=json.dumps({'company_id': tenant_id, **payload}).encode(),
        headers={'Content-Type': 'application/json', 'X-Internal-Token': token},
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False
