from datetime import date
from typing import Sequence, Set

from telebot import TeleBot

from logger.app_logger import logger
from resources.user_data import UserData
from tg.metrics import ApplicationMetrics
from tg.utils import format_user_identity


def missing_account_fields(
    accounts: Sequence[UserData],
    required_names: Set[str],
    reminder_date: date,
) -> list[tuple[UserData, Set[str]]]:
    account_fields = [
        (
            user,
            {
                resource_name
                for resource_name in required_names
                if user.get_updated_on(resource_name) != reminder_date
            },
        )
        for user in accounts
    ]
    return [
        (user, missing_names)
        for user, missing_names in account_fields
        if missing_names
    ]


def record_skipped_reminder(
    metrics: ApplicationMetrics,
    reminder,
    user_id: int,
    accounts: Sequence[UserData],
) -> None:
    metrics.reminders.labels(kind=reminder.kind.value, result="skipped").inc()
    logger.debug(
        "Resource reminder skipped for user_id=%s username=%s: all resources are current",
        user_id,
        format_user_identity(
            accounts[0].username.value, accounts[0].tag.value
        ),
    )


def deliver_reminder(
    bot: TeleBot,
    database,
    metrics: ApplicationMetrics,
    reminder,
    user_id: int,
    accounts: Sequence[UserData],
    text: str,
    keyboard,
    blocked_error_type: type[Exception],
) -> bool:
    try:
        bot.send_message(user_id, text, reply_markup=keyboard)
        metrics.reminders.labels(kind=reminder.kind.value, result="sent").inc()
        return True
    except Exception as error:
        metrics.reminders.labels(kind=reminder.kind.value, result="failed").inc()
        is_blocked = (
            isinstance(error, blocked_error_type)
            and error.error_code == 403
            and "bot was blocked by the user" in error.description.lower()
        )
        if is_blocked:
            database.set_reminders_enabled(user_id, False)
            logger.info(
                "Resource reminders disabled after bot block for user_id=%s",
                user_id,
            )
        logger.warning(
            "Unable to send resource reminder to user_id=%s username=%s: %s",
            user_id,
            format_user_identity(
                accounts[0].username.value, accounts[0].tag.value
            ),
            error,
        )
        return False
