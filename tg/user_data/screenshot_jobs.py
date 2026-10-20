"""Bounded screenshot work; completions run on the Telegram handler queue."""

from collections import Counter, deque
from dataclasses import dataclass, field
from functools import partial
from threading import Condition, Thread
from time import monotonic
from typing import Callable

from logger.app_logger import logger
from tg.metrics import APPLICATION_METRICS, ApplicationMetrics


@dataclass(eq=False)
class ScreenshotJob:
    user_id: int
    session_id: str
    run: Callable
    complete: Callable
    discard: Callable | None = None
    queued_at: float = field(default=0.0, init=False)


class ScreenshotWorker:
    def _discard(self, job: ScreenshotJob, result, error) -> None:
        if job.discard is not None:
            try:
                job.discard(result, error)
            except Exception as failure:
                logger.warning("Unable to discard screenshot result user_id=%s type=%s",
                               job.user_id, type(failure).__name__)

    def _release(self, job: ScreenshotJob) -> bool:
        if job not in self._pending:
            return False
        self._pending.remove(job)
        self._users[job.user_id] -= 1
        if not self._users[job.user_id]:
            del self._users[job.user_id]
        return True

    def _deliver(self, job: ScreenshotJob, result, error) -> None:
        with self._condition:
            accepted = self._release(job)
        if accepted:
            try:
                job.complete(result, error)
            finally:
                self._metrics.screenshot_stage_duration.labels(stage="total").observe(
                    max(0.0, self._clock() - job.queued_at)
                )
        else:
            self._discard(job, result, error)

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._stopped)
                if self._stopped:
                    return
                job = self._queue.popleft()
                self._metrics.screenshot_queue_size.set(len(self._queue))
            self._metrics.screenshot_stage_duration.labels(stage="queue").observe(
                max(0.0, self._clock() - job.queued_at)
            )
            result, error = None, None
            try:
                result = job.run()
            except Exception as failure:
                # Download errors may contain private Telegram file URLs.
                error = type(failure).__name__
                logger.warning("Screenshot background job failed type=%s", error)
            with self._condition:
                accepted = job in self._pending
                if accepted:
                    try:
                        self._dispatch(partial(self._deliver, job, result, error))
                    except Exception as failure:
                        self._release(job)
                        accepted = False
                        logger.warning(
                            "Unable to dispatch screenshot result type=%s",
                            type(failure).__name__,
                        )
            if not accepted:
                self._discard(job, result, error)

    def __init__(self, dispatch: Callable, *, per_user=10, total=30,
                 metrics: ApplicationMetrics = APPLICATION_METRICS, clock: Callable = monotonic):
        self._dispatch = dispatch
        self._metrics = metrics
        self._clock = clock
        self._per_user = per_user
        self._total = total
        self._condition = Condition()
        self._queue = deque()
        self._metrics.screenshot_queue_size.set(0)
        self._pending: set[ScreenshotJob] = set()
        self._users = Counter()
        self._stopped = False
        self._thread = Thread(target=self._run, name="screenshot-ocr", daemon=True)
        self._thread.start()

    def submit(self, job: ScreenshotJob) -> bool:
        with self._condition:
            if (self._stopped or len(self._pending) >= self._total
                    or self._users[job.user_id] >= self._per_user):
                return False
            self._pending.add(job)
            self._users[job.user_id] += 1
            job.queued_at = self._clock()
            self._queue.append(job)
            self._metrics.screenshot_queue_size.set(len(self._queue))
            self._condition.notify()
            return True

    def cancel(self, session_id: str) -> None:
        with self._condition:
            for job in tuple(self._pending):
                if job.session_id == session_id:
                    self._release(job)
            self._queue = deque(job for job in self._queue if job in self._pending)
            self._metrics.screenshot_queue_size.set(len(self._queue))

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._users.clear()
            self._queue.clear()
            self._metrics.screenshot_queue_size.set(0)
            self._condition.notify()
        self._thread.join(timeout=2)
