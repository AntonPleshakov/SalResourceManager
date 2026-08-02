from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import Event, Thread
from typing import Callable, Optional

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup

from common.datetime_utils import now
from db.user_data import get_user_data_db
from db.war_stages import get_war_stages_db
from logger.app_logger import logger
from resources.user_data import RESOURCE_FIELDS
from resources.war import WarActivity
from tg.utils import Button


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

SPENT_RESOURCES_BY_ACTIVITY = {
    WarActivity.FORGING: frozenset({"hammers"}),
    WarActivity.SKILLS: frozenset({"skills"}),
    WarActivity.MOUNTS: frozenset({"mount_keys", "unmerged_mounts"}),
    WarActivity.PETS: frozenset({"shells", "pets"}),
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


def _reminder_text(reminder: ScheduledReminder) -> str:
    if reminder.kind == ReminderKind.WEEKLY_REWARD:
        return (
            "🎁 <b>Недельные награды</b>\n\n"
            "Не забудьте обновить ресурсы, полученные в награду "
            "за войну и личный турнир."
        )

    stages = get_war_stages_db().get_stages().get(reminder.war_day, ())
    stage_titles = ", ".join(activity.title for activity in stages)
    spent_resource_names = {
        resource_name
        for activity in stages
        for resource_name in SPENT_RESOURCES_BY_ACTIVITY.get(activity, ())
    }
    spent_resource_titles = [
        field.title for field in RESOURCE_FIELDS if field.name in spent_resource_names
    ]
    text = (
        f"⏰ <b>Обновите ресурсы после {reminder.war_day}-го дня войны</b>\n\n"
        "Проверьте и обновите ресурсы, которые могли быть потрачены вчера."
    )
    if stage_titles:
        text += f"\n\nЭтапы дня: {stage_titles}."
    if spent_resource_titles:
        resources = "\n".join(f"• {title}" for title in spent_resource_titles)
        text += f"\n\n<b>Могли быть потрачены:</b>\n{resources}"
    else:
        text += "\n\nДля этих этапов нет отслеживаемых расходуемых ресурсов."
    return text


def send_reminder(bot: TeleBot, reminder: ScheduledReminder) -> None:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Обновить ресурсы", "user_data/fill/resources").inline())
    text = _reminder_text(reminder)

    sent = 0
    users = get_user_data_db().get_users()
    logger.info(
        "Sending resource reminder kind=%s war_day=%s recipients=%d",
        reminder.kind.value,
        reminder.war_day,
        len(users),
    )
    for user in users:
        user_id = user.user_id.value
        try:
            bot.send_message(user_id, text, reply_markup=keyboard)
            sent += 1
        except Exception as error:
            logger.warning(
                "Unable to send resource reminder to user_id=%s username=%s: %s",
                user_id,
                user.username.value,
                error,
            )
    logger.info("Resource reminder '%s' sent to %s users", reminder.kind, sent)


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
