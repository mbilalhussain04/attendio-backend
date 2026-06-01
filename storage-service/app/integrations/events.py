import os

try:
    from attendio_shared.events import publish_event as shared_publish_event
except ImportError:  # Local unit tests may run without the shared package on PYTHONPATH.
    shared_publish_event = None


def publish_event(event_name: str, tenant_id: str | None, payload: dict) -> bool:
    if shared_publish_event is None:
        return False
    return shared_publish_event(
        event_name=event_name,
        tenant_id=tenant_id,
        payload=payload,
        source=os.getenv("APP_NAME", "storage-service"),
    )
