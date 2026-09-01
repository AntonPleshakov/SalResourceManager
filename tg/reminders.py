from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Sequence, Set, Tuple

from telebot import TeleBot, formatting
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup

from db.initializer import get_user_data_db
from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    TECHNOLOGY_FIELDS,
    TRACKED_FIELDS,
    UserData,
)
from tg.metrics import APPLICATION_METRICS, ApplicationMetrics
from tg.scheduling import ReminderScheduler
from tg.scheduling.delivery import (
    deliver_reminder,
    missing_account_fields,
    record_skipped_reminder,
)
from tg.utils import Button, group_user_accounts


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
        "🎁 <b>Недельные награды</b>\n\n"
        "Не забудьте обновить ресурсы, полученные в награду "
        "за войну и личный турнир."
    )


def _account_reminder_text(
    reminder: ScheduledReminder,
    account_fields: Sequence[Tuple[UserData, Set[str]]],
) -> str:
    blocks = []
    for index, (user, field_names) in enumerate(account_fields, start=1):
        tag = str(user.tag.value).strip() or f"Аккаунт {index}"
        fields = "\n".join(
            f"• {field.title}"
            for field in TRACKED_FIELDS
            if field.name in field_names
        )
        blocks.append(f"<b>{formatting.escape_html(tag)}</b>\n{fields}")
    return (
        f"{_reminder_intro()}\n\n<b>Не обновлены сегодня:</b>\n\n"
        + "\n\n".join(blocks)
    )


def _reminder_keyboard(
    field_names: Set[str],
    account_fields: Optional[Sequence[Tuple[UserData, Set[str]]]] = None,
    multiple_accounts: bool = False,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    if multiple_accounts and account_fields is not None:
        resource_names = {field.name for field in RESOURCE_FIELDS}
        technology_names = {field.name for field in TECHNOLOGY_FIELDS}
        for index, (user, missing_names) in enumerate(account_fields, start=1):
            tag = str(user.tag.value).strip() or f"Аккаунт {index}"
            account_id = user.account_id.value
            if missing_names & resource_names:
                keyboard.add(
                    Button(
                        f"📦 Ресурсы · {tag}",
                        f"accounts/select/resources/{account_id}",
                    ).inline()
                )
            if missing_names & technology_names:
                keyboard.add(
                    Button(
                        f"🔬 Технологии · {tag}",
                        f"accounts/select/technologies/{account_id}",
                    ).inline()
                )
        keyboard.add(Button("⬅️ Назад в меню", "home").inline())
        return keyboard

    field_indexes = ",".join(
        str(index)
        for index, field in enumerate(TRACKED_FIELDS)
        if field.name in field_names
    )
    if field_indexes:
        keyboard.add(
            Button(
                "📝 Обновить данные",
                f"user_data/fill/tracked/{field_indexes}",
            ).inline()
        )
    keyboard.row(
        Button("📦 Ресурсы", "resources").inline(),
        Button("🔬 Технологии", "technologies").inline(),
    )
    keyboard.add(Button("🐾 Питомцы", "pets").inline())
    keyboard.add(Button("⬅️ Назад в меню", "home").inline())
    return keyboard


def send_reminder(
    bot: TeleBot,
    reminder: ScheduledReminder,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
) -> None:
    sent = 0
    skipped = 0
    database = get_user_data_db()
    users = database.get_users_with_reminders_enabled()
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
        missing_names = {
            field_name
            for account_field in account_fields
            for field_name in account_field[1]
        }
        keyboard = _reminder_keyboard(
            missing_names,
            account_fields if len(accounts) > 1 else None,
            multiple_accounts=len(accounts) > 1,
        )
        if deliver_reminder(
            bot,
            database,
            metrics,
            reminder,
            user_id,
            accounts,
            _account_reminder_text(reminder, account_fields),
            keyboard,
            ApiTelegramException,
        ):
            sent += 1
    logger.info(
        "Resource reminder '%s' sent=%d skipped=%d",
        reminder.kind.value,
        sent,
        skipped,
    )
