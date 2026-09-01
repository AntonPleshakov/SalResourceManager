from datetime import datetime, timedelta, timezone


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


def now() -> datetime:
    return datetime.now(MOSCOW_TIMEZONE)
