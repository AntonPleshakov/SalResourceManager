import logging
from pathlib import Path

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from logger.app_logger import _MaxLevelFilter, _gdrive_logging_enabled


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord("test", level, "", 0, "", (), None)


def test_stdout_filter_only_allows_debug_and_info():
    log_filter = _MaxLevelFilter(logging.INFO)

    assert log_filter.filter(_record(logging.DEBUG))
    assert log_filter.filter(_record(logging.INFO))
    assert not log_filter.filter(_record(logging.WARNING))


def test_gdrive_logging_can_be_disabled_by_environment(monkeypatch):
    monkeypatch.setenv("LOG_TO_GDRIVE", "false")

    assert not _gdrive_logging_enabled()


def test_gdrive_logging_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LOG_TO_GDRIVE", raising=False)

    assert not _gdrive_logging_enabled()
