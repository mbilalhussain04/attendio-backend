
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///" + str(ROOT / "test_auth.db"))
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("AUTH_BASE_DOMAIN", "auth.lvh.me")
os.environ.setdefault("DEFAULT_ROOT_DOMAIN", "lvh.me")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import Base, engine
from app.models import base  # noqa

Base.metadata.create_all(bind=engine)
