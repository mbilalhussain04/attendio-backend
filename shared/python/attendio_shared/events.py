from __future__ import annotations
import json, os
from typing import Any
from urllib import request
from .contracts import EventEnvelope

try:
    import redis
except Exception:  # pragma: no cover
    redis = None

try:
    import pika
except Exception:  # pragma: no cover
    pika = None


def publish_event(event_name: str, tenant_id: str | None, payload: dict[str, Any], source: str = 'service') -> bool:
    backend = os.getenv('INTERNAL_EVENT_BACKEND', 'redis').lower()
    envelope = EventEnvelope(event_name=event_name, tenant_id=tenant_id, payload=payload, source=source)
    body = envelope.model_dump_json()
    if backend == 'rabbitmq':
        url = os.getenv('RABBITMQ_URL')
        if not url or pika is None:
            return _publish_http_fallback(event_name, tenant_id, payload)
        try:
            params = pika.URLParameters(url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.exchange_declare(exchange='attendio.events', exchange_type='topic', durable=True)
            channel.basic_publish(exchange='attendio.events', routing_key=event_name, body=body)
            connection.close()
            return True
        except Exception:
            return _publish_http_fallback(event_name, tenant_id, payload)
    if backend == 'redis':
        url = os.getenv('REDIS_URL')
        if not url or redis is None:
            return _publish_http_fallback(event_name, tenant_id, payload)
        try:
            client = redis.Redis.from_url(url, decode_responses=True)
            client.publish('attendio.events', body)
            return True
        except Exception:
            return _publish_http_fallback(event_name, tenant_id, payload)
    return _publish_http_fallback(event_name, tenant_id, payload)


def _publish_http_fallback(event_name: str, tenant_id: str | None, payload: dict[str, Any]) -> bool:
    """Keep local development functional when a broker is unavailable."""
    if event_name != 'notification.requested' or not tenant_id:
        return False
    base_url = os.getenv('NOTIFICATION_SERVICE_URL')
    token = os.getenv('INTERNAL_SERVICE_TOKEN')
    if not base_url or not token:
        return False
    body = json.dumps({'company_id': tenant_id, **payload}).encode()
    req = request.Request(
        f"{base_url.rstrip('/')}/api/v1/notifications/internal",
        data=body,
        headers={'Content-Type': 'application/json', 'X-Internal-Token': token},
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False
