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
from resources.war import WAR_STAGES, WarActivity
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
    DAILY = "daily"
    WEEKLY_REWARD = "weekly_reward"


@dataclass(frozen=True)
class ScheduledReminder:
    time: datetime
    kind: ReminderKind
    war_day: Optional[int] = None


# Tuesday through Saturday are war days 1 through 5. Their reminders are sent
# on the following day, Wednesday through Sunday. Monday has a separate reminder.
REMINDERS_BY_WEEKDAY = {
    0: (ReminderKind.WEEKLY_REWARD, None),
    2: (ReminderKind.DAILY, 1),
    3: (ReminderKind.DAILY, 2),
    4: (ReminderKind.DAILY, 3),
    5: (ReminderKind.DAILY, 4),
    6: (ReminderKind.DAILY, 5),
}

UPDATED_FIELDS_BY_ACTIVITY = {
    WarActivity.FORGING: frozenset({"hammers"}),
    WarActivity.SKILLS: frozenset({"skills"}),
    WarActivity.MOUNTS: frozenset({"mount_keys", "unmerged_mounts"}),
    WarActivity.PETS: frozenset({"shells", "pets"}),
    WarActivity.FORGE: frozenset({"forge_level"}),
    WarActivity.TECHNOLOGIES: frozenset(
        field.name for field in TECHNOLOGY_FIELDS
    ),
}


def next_reminders(
    moment: datetime, hour: int = REMINDER_HOUR
) -> dict[ReminderKind, ScheduledReminder]:
    if moment.tzinfo is None:
        raise ValueError("Reminder time must be timezone-aware")
    if not 0 <= hour <= 23:
        raise ValueError("Reminder hour must be between 0 and 23")

    reminders: dict[ReminderKind, ScheduledReminder] = {}
    for days_ahead in range(8):
        day = moment + timedelta(days=days_ahead)
        reminder = REMINDERS_BY_WEEKDAY.get(day.weekday())
        if reminder is None:
            continue
        candidate = day.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate < moment:
            continue
        kind, war_day = reminder
        reminders.setdefault(kind, ScheduledReminder(candidate, kind, war_day))
        if len(reminders) == len(ReminderKind):
            return reminders

    raise RuntimeError("Unable to find all next resource reminders")


def next_reminder(moment: datetime, hour: int = REMINDER_HOUR) -> ScheduledReminder:
    return min(next_reminders(moment, hour).values(), key=lambda item: item.time)


def _required_field_names(reminder: ScheduledReminder) -> Set[str]:
    if reminder.kind == ReminderKind.WEEKLY_REWARD:
        return {field.name for field in RESOURCE_FIELDS}

    stages = WAR_STAGES.get(reminder.war_day, ())
    return {
        resource_name
        for activity in stages
        for resource_name in UPDATED_FIELDS_BY_ACTIVITY.get(activity, ())
    }


def _reminder_intro(reminder: ScheduledReminder) -> str:
    if reminder.kind == ReminderKind.WEEKLY_REWARD:
        return (
            "🎁 <b>Недельные награды</b>\n\n"
            "Не забудьте обновить ресурсы, полученные в награду "
            "за войну и личный турнир."
        )

    stages = WAR_STAGES.get(reminder.war_day, ())
    stage_titles = ", ".join(activity.title for activity in stages)
    text = (
        f"⏰ <b>Обновите данные после {reminder.war_day}-го дня войны</b>\n\n"
        "Проверьте и обновите показатели, которые могли измениться вчера."
    )
    if stage_titles:
        text += f"\n\nЭтапы дня: {stage_titles}."
    return text


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
        f"{_reminder_intro(reminder)}\n\n<b>Не обновлены сегодня:</b>\n\n"
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
    required_names = _required_field_names(reminder)
    logger.info(
        "Sending resource reminder kind=%s war_day=%s recipients=%d resources=%d",
        reminder.kind.value,
        reminder.war_day,
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
