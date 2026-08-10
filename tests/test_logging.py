import logging
from pathlib import Path

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from logger.app_logger import _MaxLevelFilter, _build_logger


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord("test", level, "", 0, "", (), None)


def test_stdout_filter_only_allows_debug_and_info():
    log_filter = _MaxLevelFilter(logging.INFO)

    assert log_filter.filter(_record(logging.DEBUG))
    assert log_filter.filter(_record(logging.INFO))
    assert not log_filter.filter(_record(logging.WARNING))


def test_build_logger_replaces_only_application_handlers(monkeypatch):
    custom_handler = logging.NullHandler()
    app_logger = logging.getLogger("SalResourcesManager")
    app_logger.addHandler(custom_handler)

    try:
        rebuilt_logger = _build_logger()
        rebuilt_logger = _build_logger()

        managed_handlers = [
            handler
            for handler in rebuilt_logger.handlers
            if getattr(handler, "_sal_managed", False)
        ]
        assert len(managed_handlers) == 2
        assert custom_handler in rebuilt_logger.handlers
    finally:
        app_logger.removeHandler(custom_handler)
