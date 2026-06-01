import json, os, threading
try:
    import redis
except Exception:
    redis = None
try:
    import pika
except Exception:
    pika = None
from app.db.session import SessionLocal
from app.services.notifications import service

def handle_event(body: str):
    event = json.loads(body)
    if event.get("event_name") != "notification.requested":
        return
    payload = event.get("payload") or {}
    payload["company_id"] = event.get("tenant_id")
    with SessionLocal() as db:
        service.create(db, payload=payload)

def start_consumer():
    backend = os.getenv("INTERNAL_EVENT_BACKEND", "redis").lower()
    def run():
        if backend == "rabbitmq" and pika is not None:
            connection = pika.BlockingConnection(pika.URLParameters(os.getenv("RABBITMQ_URL")))
            channel = connection.channel()
            channel.exchange_declare(exchange="attendio.events", exchange_type="topic", durable=True)
            queue = channel.queue_declare(queue="notification-service.events", durable=True)
            channel.queue_bind(exchange="attendio.events", queue=queue.method.queue, routing_key="notification.#")
            channel.basic_consume(queue=queue.method.queue, auto_ack=True, on_message_callback=lambda _ch, _method, _props, body: handle_event(body.decode()))
            channel.start_consuming()
        elif backend == "redis" and redis is not None:
            client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            pubsub = client.pubsub()
            pubsub.subscribe("attendio.events")
            for message in pubsub.listen():
                if message.get("type") == "message":
                    try: handle_event(message["data"])
                    except Exception: continue
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
