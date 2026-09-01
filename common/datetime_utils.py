from datetime import date, datetime, timedelta, timezone


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))
WEEK_START_HOUR = 3


def now() -> datetime:
    return datetime.now(MOSCOW_TIMEZONE)


def week_started_on(reference: datetime) -> date:
    shifted_reference = reference - timedelta(hours=WEEK_START_HOUR)
    return shifted_reference.date() - timedelta(
        days=shifted_reference.weekday()
    )
