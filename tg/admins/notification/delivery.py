from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from telebot import TeleBot

from logger.app_logger import logger
from resources.user_data import UserData
from tg.admins.notification.content import (
    BroadcastResult,
    StandardNotificationPlan,
)
from tg.utils import format_user_identity


Item = TypeVar("Item")


def _broadcast(
    items: Iterable[Item],
    deliver: Callable[[Item], None],
    log_failure: Callable[[Item, Exception], None],
) -> BroadcastResult:
    sent = 0
    failed = 0
    for item in items:
        try:
            deliver(item)
            sent += 1
        except Exception as error:
            failed += 1
            log_failure(item, error)
    return BroadcastResult(sent, failed)


def send_standard(bot: TeleBot, plan: StandardNotificationPlan) -> BroadcastResult:
    logger.info(
        "Starting standard admin notification recipients=%d",
        len(plan.recipients),
    )

    def deliver(recipient) -> None:
        bot.send_message(
            recipient.user_id,
            recipient.text,
            reply_markup=recipient.keyboard,
        )

    def log_failure(recipient, error: Exception) -> None:
        logger.warning(
            "Unable to send admin notification to user_id=%s username=%s: %s",
            recipient.user_id,
            recipient.identity,
            error,
        )

    result = _broadcast(plan.recipients, deliver, log_failure)
    logger.info(
        "Standard admin notification sent=%s failed=%s skipped=%s",
        result.sent,
        result.failed,
        plan.skipped,
    )
    return result


def send_group(
    bot: TeleBot,
    group_id: int,
    messages: Iterable[str],
    recipient_count: int,
) -> BroadcastResult:
    messages = tuple(messages)
    logger.info(
        "Starting custom group notification recipients=%d chunks=%d",
        recipient_count,
        len(messages),
    )

    def deliver(message: str) -> None:
        bot.send_message(group_id, message, disable_notification=False)

    def log_failure(_: str, error: Exception) -> None:
        logger.warning("Unable to send custom admin notification: %s", error)

    result = _broadcast(messages, deliver, log_failure)
    logger.info(
        "Custom admin notification sent=%s failed=%s",
        result.sent,
        result.failed,
    )
    return result


def send_private(
    bot: TeleBot,
    message: str,
    grouped_users: dict[int, Sequence[UserData]],
) -> BroadcastResult:
    logger.info(
        "Starting custom private notification recipients=%d", len(grouped_users)
    )

    def deliver(item: tuple[int, Sequence[UserData]]) -> None:
        bot.send_message(item[0], message, disable_notification=False)

    def log_failure(
        item: tuple[int, Sequence[UserData]], error: Exception
    ) -> None:
        user_id, accounts = item
        logger.warning(
            "Unable to send custom private notification to user_id=%s username=%s: %s",
            user_id,
            format_user_identity(
                accounts[0].username.value, accounts[0].tag.value
            ),
            error,
        )

    result = _broadcast(grouped_users.items(), deliver, log_failure)
    logger.info(
        "Custom private notification sent=%s failed=%s",
        result.sent,
        result.failed,
    )
    return result
