"""Weekly scheduler for clan administrator access reconciliation."""

from datetime import datetime, timedelta
from threading import Event, Thread
from typing import Callable, Optional

from telebot import TeleBot

from common.datetime_utils import now
from logger.app_logger import logger


ADMIN_RECONCILIATION_WEEKDAY = 6
ADMIN_RECONCILIATION_HOUR = 20


def next_admin_reconciliation(
    moment: datetime,
    hour: int = ADMIN_RECONCILIATION_HOUR,
) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("Admin reconciliation time must be timezone-aware")
    if not 0 <= hour <= 23:
        raise ValueError("Admin reconciliation hour must be between 0 and 23")

    days_ahead = (ADMIN_RECONCILIATION_WEEKDAY - moment.weekday()) % 7
    candidate = (moment + timedelta(days=days_ahead)).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate < moment:
        candidate += timedelta(days=7)
    return candidate


class AdminReconciliationScheduler:
    def __init__(
        self,
        bot: TeleBot,
        hour: int = ADMIN_RECONCILIATION_HOUR,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self._bot = bot
        self._hour = hour
        self._clock = clock
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def _run(self) -> None:
        from tg.admins.reconciliation import reconcile_clan_admins

        while not self._stop_event.is_set():
            scheduled_at = next_admin_reconciliation(
                self._clock(), self._hour
            )
            delay = max(
                (scheduled_at - self._clock()).total_seconds(),
                0,
            )
            logger.debug(
                "Next clan admin reconciliation scheduled_at=%s "
                "delay_seconds=%.0f",
                scheduled_at.isoformat(),
                delay,
            )
            if self._stop_event.wait(delay):
                return
            try:
                reconcile_clan_admins(self._bot)
            except Exception:
                logger.exception("Unable to reconcile clan administrator access")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="admin-reconciliation",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Clan admin reconciliation scheduler started: Sunday at %02d:00",
            self._hour,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.warning(
                    "Clan admin reconciliation scheduler did not stop in time"
                )
