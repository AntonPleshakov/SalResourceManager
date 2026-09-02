from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from html import escape
from typing import Sequence, Set, Tuple

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InputRichMessage

from db.initializer import get_user_data_db
from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    TECHNOLOGY_FIELDS,
    TRACKED_FIELDS,
    UserData,
)
from tg.metrics import APPLICATION_METRICS, ApplicationMetrics
from tg.rich import button_row, callback_button, input_rich_message
from tg.clans import refresh_clan_accounts
from tg.scheduling import ReminderScheduler
from tg.scheduling.delivery import (
    deliver_reminder,
    missing_account_fields,
    record_skipped_reminder,
)
from tg.utils import group_user_accounts


REMINDER_HOUR = 13


class ReminderKind(str, Enum):
    WEEKLY_REWARD = "weekly_reward"


@dataclass(frozen=True)
class ScheduledReminder:
    time: datetime
    kind: ReminderKind


def next_reminder(moment: datetime, hour: int = REMINDER_HOUR) -> ScheduledReminder:
    if moment.tzinfo is None:
        raise ValueError("Reminder time must be timezone-aware")
    if not 0 <= hour <= 23:
        raise ValueError("Reminder hour must be between 0 and 23")

    for days_ahead in range(8):
        day = moment + timedelta(days=days_ahead)
        if day.weekday() != 0:
            continue
        candidate = day.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate < moment:
            continue
        return ScheduledReminder(candidate, ReminderKind.WEEKLY_REWARD)

    raise RuntimeError("Unable to find the next resource reminder")


def _required_field_names() -> Set[str]:
    return {field.name for field in RESOURCE_FIELDS}


def _reminder_intro() -> str:
    return (
        "<h2>🎁 Недельные награды</h2>"
        "<p>Не забудьте обновить ресурсы, полученные в награду "
        "за войну и личный турнир.</p>"
    )


def _account_reminder_block(
    user: UserData, field_names: Set[str], index: int
) -> str:
    tag = str(user.tag.value).strip() or f"Аккаунт {index}"
    fields = "".join(
        f"<li>{escape(field.title)}</li>"
        for field in TRACKED_FIELDS
        if field.name in field_names
    )
    return f"<h3>{escape(tag)}</h3><ul>{fields}</ul>"


def _account_reminder_text(
    reminder: ScheduledReminder,
    account_fields: Sequence[Tuple[UserData, Set[str]]],
) -> str:
    blocks = "".join(
        _account_reminder_block(user, field_names, index)
        for index, (user, field_names) in enumerate(account_fields, start=1)
    )
    return (
        f"{_reminder_intro()}<p><b>Не обновлены сегодня:</b></p>"
        f"{blocks}"
    )


def _tracked_field_indexes(field_names: Set[str]) -> str:
    return ",".join(
        str(index)
        for index, field in enumerate(TRACKED_FIELDS)
        if field.name in field_names
    )


def _account_buttons(user: UserData, field_names: Set[str], index: int) -> str:
    tag = str(user.tag.value).strip() or f"Аккаунт {index}"
    account_id = user.account_id.value
    resource_names = {field.name for field in RESOURCE_FIELDS}
    technology_names = {field.name for field in TECHNOLOGY_FIELDS}
    buttons = []
    if field_names & resource_names:
        buttons.append(
            callback_button(
                f"📦 Ресурсы · {tag}",
                f"accounts/select/resources/{account_id}",
                style="primary",
            )
        )
    if field_names & technology_names:
        buttons.append(
            callback_button(
                f"🔬 Технологии · {tag}",
                f"accounts/select/technologies/{account_id}",
                style="primary",
            )
        )
    return button_row(buttons) if buttons else ""


def _reminder_buttons(
    field_names: Set[str],
) -> str:
    field_indexes = _tracked_field_indexes(field_names)
    parts = []
    if field_indexes:
        parts.append(
            button_row(
                (
                    callback_button(
                        "📝 Обновить данные",
                        f"user_data/fill/tracked/{field_indexes}",
                        style="primary",
                    ),
                )
            )
        )
    parts.append(
        button_row(
            (
                callback_button("📦 Ресурсы", "resources"),
                callback_button("🔬 Технологии", "technologies"),
            )
        )
    )
    parts.append(
        button_row((callback_button("🐾 Питомцы", "pets"),))
    )
    parts.append(
        button_row(
            (callback_button("⬅️ Назад в меню", "home"),),
            align="left",
        )
    )
    return "".join(parts)


def _account_reminder_message(
    reminder: ScheduledReminder,
    account_fields: Sequence[Tuple[UserData, Set[str]]],
    *,
    multiple_accounts: bool = False,
) -> InputRichMessage:
    missing_names = {
        field_name
        for account_field in account_fields
        for field_name in account_field[1]
    }
    if multiple_accounts:
        account_blocks = "".join(
            _account_reminder_block(user, field_names, index)
            + _account_buttons(user, field_names, index)
            for index, (user, field_names) in enumerate(
                account_fields, start=1
            )
        )
        html = (
            f"{_reminder_intro()}<p><b>Не обновлены сегодня:</b></p>"
            f"{account_blocks}"
            + button_row(
                (callback_button("⬅️ Назад в меню", "home"),),
                align="left",
            )
        )
    else:
        html = _account_reminder_text(reminder, account_fields)
        html += _reminder_buttons(missing_names)
    return input_rich_message((html,))


def send_reminder(
    bot: TeleBot,
    reminder: ScheduledReminder,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
) -> None:
    sent = 0
    skipped = 0
    database = get_user_data_db()
    for clan_id in database.get_attached_clan_ids():
        refresh_clan_accounts(bot, clan_id, database)
    users = database.get_assigned_users_with_reminders_enabled()
    required_names = _required_field_names()
    logger.info(
        "Sending resource reminder kind=%s recipients=%d resources=%d",
        reminder.kind.value,
        len(group_user_accounts(users)),
        len(required_names),
    )
    for user_id, accounts in group_user_accounts(users).items():
        account_fields = missing_account_fields(
            accounts, required_names, reminder.time.date()
        )
        if not account_fields:
            skipped += 1
            record_skipped_reminder(metrics, reminder, user_id, accounts)
            continue
        if deliver_reminder(
            bot,
            database,
            metrics,
            reminder,
            user_id,
            accounts,
            _account_reminder_message(
                reminder,
                account_fields,
                multiple_accounts=len(accounts) > 1,
            ),
            ApiTelegramException,
        ):
            sent += 1
    logger.info(
        "Resource reminder '%s' sent=%d skipped=%d",
        reminder.kind.value,
        sent,
        skipped,
    )
