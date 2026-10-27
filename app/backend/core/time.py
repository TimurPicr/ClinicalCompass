from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Reporting days in this Russian-language local demo use Moscow time.
REPORT_ZONE = ZoneInfo("Europe/Moscow")


def report_date():
    return datetime.now(REPORT_ZONE).date()


def as_utc(value: datetime):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
