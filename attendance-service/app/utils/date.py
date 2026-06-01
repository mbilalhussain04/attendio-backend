from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from app.core.config import settings


def today_date() -> date:
    return datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()


def local_date_for(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(settings.DEFAULT_TIMEZONE)).date()


def today_range() -> tuple[datetime, datetime]:
    start = datetime.combine(today_date(), datetime.min.time())
    end = start + timedelta(days=1)
    return start, end


def parse_range(from_date: str | None, to_date: str | None) -> tuple[date, date]:
    today = today_date()
    start = date.fromisoformat(from_date) if from_date else today.replace(day=1)
    end = date.fromisoformat(to_date) if to_date else today
    return start, end
