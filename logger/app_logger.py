import logging
import sys

from config.config import getconf
from .RotatingGDriveHandler import RotatingGDriveHandler


def _build_logger() -> logging.Logger:
    formatter = logging.Formatter(getconf("LOG_FORMAT"), getconf("LOG_DATE_FORMAT"))
    file_handler = RotatingGDriveHandler(
        getconf("LOG_FILE_NAME"), max_bytes=100_000, backup_count=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(formatter)

    result = logging.getLogger("SalResourcesManager")
    result.setLevel(logging.DEBUG)
    result.addHandler(stream_handler)
    result.addHandler(file_handler)
    return result


logger = _build_logger()
bot_logger = logging.getLogger("TeleBot")
bot_logger.setLevel(logging.INFO)
