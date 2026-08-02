import logging
import os
import sys

from config.config import getconf


class _MaxLevelFilter(logging.Filter):
    def __init__(self, maximum_level: int):
        super().__init__()
        self._maximum_level = maximum_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._maximum_level


def _gdrive_logging_enabled() -> bool:
    value = os.getenv("LOG_TO_GDRIVE", "false")
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

    if _gdrive_logging_enabled():
        from .RotatingGDriveHandler import RotatingGDriveHandler

        file_handler = RotatingGDriveHandler(
            getconf("LOG_FILE_NAME"), max_bytes=100_000, backup_count=5
        )
        file_handler._sal_managed = True
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        result.addHandler(file_handler)
        result.info("Google Drive log persistence enabled")
    return result


logger = _build_logger()
bot_logger = logging.getLogger("TeleBot")
bot_logger.setLevel(logging.INFO)
