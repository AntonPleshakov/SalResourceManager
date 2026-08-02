import time
from typing import Callable, List, Optional, TypeVar

from googleapiclient.errors import HttpError
from pygsheets.exceptions import RequestError
from requests.exceptions import RequestException

from logger.app_logger import logger


T = TypeVar("T")


def is_retryable(error: Exception) -> bool:
    if isinstance(error, HttpError):
        return error.resp.status == 429 or 500 <= error.resp.status < 600
    return isinstance(
        error,
        (ConnectionError, TimeoutError, RequestError, RequestException),
    )


def run_with_backoff(
    operation: Callable[[], T],
    *,
    timeout_seconds: float = 60,
    initial_delay_seconds: float = 1,
    max_delay_seconds: float = 15,
) -> T:
    started_at = time.monotonic()
    delay = initial_delay_seconds
    attempt = 1

    while True:
        try:
            result = operation()
            if attempt > 1:
                logger.info("Startup initialization succeeded on attempt %d", attempt)
            return result
        except Exception as error:
            if not is_retryable(error):
                logger.error(
                    "Startup initialization failed with a non-retryable %s",
                    type(error).__name__,
                )
                raise

            remaining = timeout_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                logger.error(
                    "Startup initialization timed out after %d attempts",
                    attempt,
                )
                raise

            retry_delay = min(delay, remaining)
            logger.warning(
                "Startup initialization attempt %d failed: %s. "
                "Retrying in %.1f seconds",
                attempt,
                error,
                retry_delay,
            )
            time.sleep(retry_delay)
            attempt += 1
            delay = min(delay * 2, max_delay_seconds)


class ReconnectableDB:
    def _reconnect(self) -> None:
        raise NotImplementedError

    def _run_with_retry(
        self,
        operation: Callable[[], T],
        should_retry: Optional[Callable[[], bool]] = None,
    ) -> Optional[T]:
        try:
            return operation()
        except Exception as error:
            if not is_retryable(error):
                logger.error(
                    "%s request failed with a non-retryable %s",
                    type(self).__name__,
                    type(error).__name__,
                )
                raise
            logger.warning(
                "%s request failed with %s; reconnecting before retry",
                type(self).__name__,
                type(error).__name__,
            )
            self._reconnect()
            if should_retry is not None and not should_retry():
                logger.info(
                    "%s retry skipped because the operation was already applied",
                    type(self).__name__,
                )
                return None
            result = operation()
            logger.info("%s request succeeded after reconnect", type(self).__name__)
            return result

    def _add_row_with_retry(
        self, row: List[str], should_retry: Callable[[], bool]
    ) -> bool:
        def add_row() -> bool:
            self._manager.add_row(row)
            return True

        return bool(self._run_with_retry(add_row, should_retry))
