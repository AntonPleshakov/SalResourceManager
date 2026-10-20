"""Bounded screenshot work; completions run on the Telegram handler queue."""

from collections import Counter, deque
from dataclasses import dataclass
from functools import partial
from threading import Condition, Thread
from typing import Callable

from logger.app_logger import logger


@dataclass(eq=False)
class ScreenshotJob:
    user_id: int
    session_id: str
    run: Callable
    complete: Callable


class ScreenshotWorker:
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
            job.complete(result, error)

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._stopped)
                if self._stopped:
                    return
                job = self._queue.popleft()
            result, error = None, None
            try:
                result = job.run()
            except Exception as failure:
                # Download errors may contain private Telegram file URLs.
                error = type(failure).__name__
                logger.warning("Screenshot background job failed type=%s", error)
            with self._condition:
                if job not in self._pending:
                    continue
                try:
                    self._dispatch(partial(self._deliver, job, result, error))
                except Exception as failure:
                    self._release(job)
                    logger.warning(
                        "Unable to dispatch screenshot result type=%s",
                        type(failure).__name__,
                    )

    def __init__(self, dispatch: Callable, *, per_user=10, total=30):
        self._dispatch = dispatch
        self._per_user = per_user
        self._total = total
        self._condition = Condition()
        self._queue = deque()
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
            self._queue.append(job)
            self._condition.notify()
            return True

    def cancel(self, session_id: str) -> None:
        with self._condition:
            for job in tuple(self._pending):
                if job.session_id == session_id:
                    self._release(job)
            self._queue = deque(job for job in self._queue if job in self._pending)

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._users.clear()
            self._queue.clear()
            self._condition.notify()
        self._thread.join(timeout=2)
