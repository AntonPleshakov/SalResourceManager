from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import Event, Thread
from typing import Callable, Iterable, Optional, Set

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup

from common.datetime_utils import now
from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import RESOURCE_FIELDS, TECHNOLOGY_FIELDS, TRACKED_FIELDS
from resources.war import WAR_STAGES, WarActivity
from tg.utils import Button, format_user_identity


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


def next_reminder(moment: datetime, hour: int = 13) -> ScheduledReminder:
    if moment.tzinfo is None:
        raise ValueError("Reminder time must be timezone-aware")
    if not 0 <= hour <= 23:
        raise ValueError("Reminder hour must be between 0 and 23")

    for days_ahead in range(8):
        day = moment + timedelta(days=days_ahead)
        reminder = REMINDERS_BY_WEEKDAY.get(day.weekday())
        if reminder is None:
            continue
        candidate = day.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate < moment:
            continue
        kind, war_day = reminder
        return ScheduledReminder(candidate, kind, war_day)

    raise RuntimeError("Unable to find the next resource reminder")


def _required_field_names(reminder: ScheduledReminder) -> Set[str]:
    if reminder.kind == ReminderKind.WEEKLY_REWARD:
        return {field.name for field in RESOURCE_FIELDS}

    stages = WAR_STAGES.get(reminder.war_day, ())
    return {
        resource_name
        for activity in stages
        for resource_name in UPDATED_FIELDS_BY_ACTIVITY.get(activity, ())
    }


def _reminder_text(
    reminder: ScheduledReminder,
    resource_names: Optional[Iterable[str]] = None,
) -> str:
    required_names = (
        set(resource_names)
        if resource_names is not None
        else _required_field_names(reminder)
    )
    field_titles = [
        field.title for field in TRACKED_FIELDS if field.name in required_names
    ]

    if reminder.kind == ReminderKind.WEEKLY_REWARD:
        text = (
            "🎁 <b>Недельные награды</b>\n\n"
            "Не забудьте обновить ресурсы, полученные в награду "
            "за войну и личный турнир."
        )
        if field_titles:
            fields = "\n".join(f"• {title}" for title in field_titles)
            text += f"\n\n<b>Не обновлены сегодня:</b>\n{fields}"
        return text

    stages = WAR_STAGES.get(reminder.war_day, ())
    stage_titles = ", ".join(activity.title for activity in stages)
    text = (
        f"⏰ <b>Обновите данные после {reminder.war_day}-го дня войны</b>\n\n"
        "Проверьте и обновите показатели, которые могли измениться вчера."
    )
    if stage_titles:
        text += f"\n\nЭтапы дня: {stage_titles}."
    if field_titles:
        fields = "\n".join(f"• {title}" for title in field_titles)
        text += f"\n\n<b>Не обновлены сегодня:</b>\n{fields}"
    else:
        text += "\n\nДля этих этапов нет отслеживаемых показателей."
    return text


def _reminder_keyboard(field_names: Set[str]) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    field_indexes = ",".join(
        str(index)
        for index, field in enumerate(TRACKED_FIELDS)
        if field.name in field_names
    )
    if field_indexes:
        keyboard.add(
            Button(
                "Обновить данные",
                f"user_data/fill/tracked/{field_indexes}",
            ).inline()
        )
    keyboard.add(Button("Ресурсы", "resources").inline())
    keyboard.add(Button("Технологии", "technologies").inline())
    keyboard.add(Button("Назад в меню", "home").inline())
    return keyboard


def send_reminder(bot: TeleBot, reminder: ScheduledReminder) -> None:
    sent = 0
    skipped = 0
    users = get_user_data_db().get_users()
    required_names = _required_field_names(reminder)
    logger.info(
        "Sending resource reminder kind=%s war_day=%s recipients=%d resources=%d",
        reminder.kind.value,
        reminder.war_day,
        len(users),
        len(required_names),
    )
    for user in users:
        user_id = user.user_id.value
        missing_names = {
            resource_name
            for resource_name in required_names
            if user.get_updated_on(resource_name) != reminder.time.date()
        }
        if not missing_names:
            skipped += 1
            logger.debug(
                "Resource reminder skipped for user_id=%s username=%s: all resources are current",
                user_id,
                format_user_identity(user.username.value, user.tag.value),
            )
            continue
        text = _reminder_text(reminder, missing_names)
        keyboard = _reminder_keyboard(missing_names)
        try:
            bot.send_message(user_id, text, reply_markup=keyboard)
            sent += 1
        except Exception as error:
            logger.warning(
                "Unable to send resource reminder to user_id=%s username=%s: %s",
                user_id,
                format_user_identity(user.username.value, user.tag.value),
                error,
            )
    logger.info(
        "Resource reminder '%s' sent=%d skipped=%d",
        reminder.kind.value,
        sent,
        skipped,
    )


class ReminderScheduler:
    def __init__(
        self,
        bot: TeleBot,
        hour: int = 13,
        clock: Callable[[], datetime] = now,
    ):
        self._bot = bot
        self._hour = hour
        self._clock = clock
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.debug("Resource reminder scheduler is already running")
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run, name="resource-reminders", daemon=True
        )
        self._thread.start()
        logger.info("Resource reminder scheduler started at %02d:00", self._hour)

    def stop(self) -> None:
        logger.info("Stopping resource reminder scheduler")
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.warning("Resource reminder scheduler did not stop in time")
            else:
                logger.info("Resource reminder scheduler stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            reminder = next_reminder(self._clock(), self._hour)
            delay = max((reminder.time - self._clock()).total_seconds(), 0)
            logger.debug(
                "Next resource reminder kind=%s scheduled_at=%s delay_seconds=%.0f",
                reminder.kind.value,
                reminder.time.isoformat(),
                delay,
            )
            if self._stop_event.wait(delay):
                logger.debug("Resource reminder scheduler received stop signal")
                return
            try:
                send_reminder(self._bot, reminder)
            except Exception:
                logger.exception("Unable to process resource reminder")
