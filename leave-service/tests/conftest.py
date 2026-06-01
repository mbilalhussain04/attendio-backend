import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///" + str(ROOT / "test_leave.db"))
os.environ.setdefault("JWT_ACCESS_SECRET", "test-secret")
os.environ.setdefault("BASE_DOMAIN", "lvh.me")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import Base
from app.db.session import engine
from app.models import *  # noqa

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
