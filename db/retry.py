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
                raise
            logger.warning("%s request failed; reconnecting before retry", type(self).__name__)
            self._reconnect()
            if should_retry is not None and not should_retry():
                return None
            return operation()

    def _add_row_with_retry(
        self, row: List[str], should_retry: Callable[[], bool]
    ) -> bool:
        def add_row() -> bool:
            self._manager.add_row(row)
            return True

        return bool(self._run_with_retry(add_row, should_retry))
