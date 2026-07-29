from datetime import datetime, timedelta, timezone
from typing import List


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


def now() -> datetime:
    return datetime.now(MOSCOW_TIMEZONE)


def _contains(elements: List[str], dt_format: str) -> bool:
    return any(value in dt_format for value in elements)


def _sync_with_default(dt: datetime, default: datetime, dt_format: str) -> datetime:
    if "%y" not in dt_format.lower():
        dt = dt.replace(year=default.year)
    if not _contains(["%b", "%B", "%m", "%-m"], dt_format):
        dt = dt.replace(month=default.month)
    if not _contains(["%a", "%w", "%d", "%-d"], dt_format.lower()):
        dt = dt.replace(day=default.day)
    return dt.replace(year=dt.year + 1) if dt < default else dt


def parse_datetime(value: str, dt_format: str, sync_with_now: bool = False) -> datetime:
    result = datetime.strptime(value, dt_format).replace(tzinfo=MOSCOW_TIMEZONE)
    return _sync_with_default(result, now(), dt_format) if sync_with_now else result
