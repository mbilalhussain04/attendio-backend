import json
import os
import threading
from datetime import date

try:
    import pika
except ImportError:
    pika = None

try:
    import redis
except ImportError:
    redis = None

from app.db.session import SessionLocal
from app.services import leave_service


def handle_event(body: str):
    event = json.loads(body)
    if event.get("event_name") != "auth.employee.registered":
        return
    company_id = event.get("tenant_id")
    payload = event.get("payload") or {}
    if not company_id or not payload.get("user_id"):
        return
    with SessionLocal() as db:
        leave_service.ensure_policy_grants(
            db,
            company_id,
            payload["user_id"],
            date.today().year,
            profile=payload,
            employee_snapshot=payload,
        )
        db.commit()


def start_consumer():
    backend = os.getenv("INTERNAL_EVENT_BACKEND", "redis").lower()

    def run():
        if backend == "rabbitmq" and pika is not None:
            connection = pika.BlockingConnection(pika.URLParameters(os.getenv("RABBITMQ_URL")))
            channel = connection.channel()
            channel.exchange_declare(exchange="attendio.events", exchange_type="topic", durable=True)
            queue = channel.queue_declare(queue="leave-service.auth-events", durable=True)
            channel.queue_bind(exchange="attendio.events", queue=queue.method.queue, routing_key="auth.employee.#")
            channel.basic_consume(queue=queue.method.queue, auto_ack=True, on_message_callback=lambda _ch, _method, _props, body: handle_event(body.decode()))
            channel.start_consuming()
        elif backend == "redis" and redis is not None:
            client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            pubsub = client.pubsub()
            pubsub.subscribe("attendio.events")
            for message in pubsub.listen():
                if message.get("type") == "message":
                    try:
                        handle_event(message["data"])
                    except Exception:
                        continue

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
