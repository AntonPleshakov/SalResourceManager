from datetime import datetime
from threading import Event, Thread
from typing import Callable, Optional

from telebot import TeleBot

from common.datetime_utils import now
from logger.app_logger import logger
from tg.metrics import APPLICATION_METRICS, ApplicationMetrics


class ReminderScheduler:
    def __init__(
        self,
        bot: TeleBot,
        hour: int = 13,
        clock: Callable[[], datetime] = now,
        metrics: ApplicationMetrics = APPLICATION_METRICS,
    ) -> None:
        self._bot = bot
        self._hour = hour
        self._clock = clock
        self._metrics = metrics
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def _run(self) -> None:
        from tg.reminders import next_reminder, send_reminder

        while not self._stop_event.is_set():
            reminder = next_reminder(self._clock(), self._hour)
            self._metrics.next_reminder_timestamp.labels(
                kind=reminder.kind.value
            ).set(reminder.time.timestamp())
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
                send_reminder(self._bot, reminder, self._metrics)
            except Exception:
                self._metrics.reminder_runs.labels(
                    kind=reminder.kind.value,
                    result="failed",
                ).inc()
                logger.exception("Unable to process resource reminder")
            else:
                self._metrics.reminder_runs.labels(
                    kind=reminder.kind.value,
                    result="completed",
                ).inc()

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
