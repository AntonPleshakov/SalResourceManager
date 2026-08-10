import logging
import sys

from config.config import getconf


class _MaxLevelFilter(logging.Filter):
    def __init__(self, maximum_level: int):
        super().__init__()
        self._maximum_level = maximum_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._maximum_level


def _build_logger() -> logging.Logger:
    formatter = logging.Formatter(getconf("LOG_FORMAT"), getconf("LOG_DATE_FORMAT"))

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler._sal_managed = True
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler._sal_managed = True
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    result = logging.getLogger("SalResourcesManager")
    result.setLevel(logging.DEBUG)
    result.propagate = False
    # Importing the module more than once must not duplicate application-owned
    # handlers. Handlers attached by a host process or a test are preserved.
    for handler in result.handlers[:]:
        if getattr(handler, "_sal_managed", False):
            result.removeHandler(handler)
            handler.close()
    result.addHandler(stdout_handler)
    result.addHandler(stderr_handler)

    return result


logger = _build_logger()
bot_logger = logging.getLogger("TeleBot")
bot_logger.setLevel(logging.INFO)
