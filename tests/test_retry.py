from pathlib import Path

import pytest

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db import retry


def test_run_with_backoff_retries_transient_errors(monkeypatch):
    attempts = 0
    delays = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Google is temporarily unavailable")
        return "connected"

    monkeypatch.setattr(retry.time, "sleep", delays.append)

    assert retry.run_with_backoff(operation) == "connected"
    assert attempts == 3
    assert delays == [1, 2]


def test_run_with_backoff_does_not_retry_permanent_errors(monkeypatch):
    def operation():
        raise ValueError("invalid configuration")

    monkeypatch.setattr(retry.time, "sleep", lambda _: pytest.fail("slept"))

    with pytest.raises(ValueError, match="invalid configuration"):
        retry.run_with_backoff(operation)


def test_run_with_backoff_stops_after_timeout(monkeypatch):
    now = 0.0
    delays = []
    attempts = 0

    def monotonic():
        return now

    def sleep(delay):
        nonlocal now
        delays.append(delay)
        now += delay

    def operation():
        nonlocal attempts
        attempts += 1
        raise ConnectionError("Google is unavailable")

    monkeypatch.setattr(retry.time, "monotonic", monotonic)
    monkeypatch.setattr(retry.time, "sleep", sleep)

    with pytest.raises(ConnectionError, match="Google is unavailable"):
        retry.run_with_backoff(operation, timeout_seconds=60)

    assert sum(delays) == 60
    assert attempts == 8
