from datetime import date, datetime, timedelta, timezone


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))
WEEK_START_HOUR = 3
DATE_FORMAT = "%d.%m.%Y"


def _days_word(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return "день"
    if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        return "дня"
    return "дней"


def now() -> datetime:
    return datetime.now(MOSCOW_TIMEZONE)


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def format_last_update(updated_on: date | None) -> str:
    if updated_on is None:
        return "никогда"

    days_ago = (now().date() - updated_on).days
    formatted_date = format_date(updated_on)
    if days_ago < 0:
        return formatted_date
    if days_ago == 0:
        relative = "сегодня"
    elif days_ago == 1:
        relative = "вчера"
    else:
        relative = f"{days_ago} {_days_word(days_ago)} назад"
    return f"{relative} ({formatted_date})"


def week_started_on(reference: datetime) -> date:
    shifted_reference = reference - timedelta(hours=WEEK_START_HOUR)
    return shifted_reference.date() - timedelta(
        days=shifted_reference.weekday()
    )
