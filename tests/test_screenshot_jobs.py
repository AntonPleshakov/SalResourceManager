from queue import Queue
from threading import Event, get_ident
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry

from tg.user_data.screenshot_jobs import ScreenshotJob, ScreenshotWorker
from tg.metrics import ApplicationMetrics


def test_slow_ocr_does_not_block_submission_and_completion_runs_on_caller_thread():
    dispatched = Queue()
    started, release = Event(), Event()
    caller_thread = get_ident()
    threads = []
    completed = Mock()

    def recognize():
        threads.append(get_ident())
        started.set()
        assert release.wait(3)
        return {"hammers": 123}

    worker = ScreenshotWorker(dispatched.put)
    try:
        assert worker.submit(ScreenshotJob(42, "session", recognize, completed))
        assert started.wait(3)
        # The blocked OCR does not prevent admitting another user's image.
        assert worker.submit(ScreenshotJob(99, "other", lambda: {}, completed))
        completed.assert_not_called()
        release.set()
        apply_result = dispatched.get(timeout=3)
        assert threads[0] != caller_thread
        apply_result()
        completed.assert_called_once_with({"hammers": 123}, None)
    finally:
        release.set()
        worker.stop()


def test_limits_include_active_jobs_and_results_waiting_for_application():
    dispatched = Queue()
    worker = ScreenshotWorker(dispatched.put, per_user=10, total=30)
    completed = Mock()
    try:
        for user in (1, 2, 3):
            for _ in range(10):
                assert worker.submit(ScreenshotJob(user, str(user), lambda: {}, completed))
        assert not worker.submit(ScreenshotJob(1, "1", lambda: {}, completed))
        assert not worker.submit(ScreenshotJob(4, "4", lambda: {}, completed))
        dispatched.get(timeout=3)()
        assert worker.submit(ScreenshotJob(4, "4", lambda: {}, completed))
    finally:
        worker.stop()


def test_cancel_discards_active_result_skips_queued_work_and_releases_capacity():
    dispatched = Queue()
    started, release = Event(), Event()
    skipped, completed = Mock(), Mock()

    def recognize():
        started.set()
        assert release.wait(3)
        return {"hammers": 123}

    worker = ScreenshotWorker(dispatched.put, per_user=2, total=2)
    try:
        assert worker.submit(ScreenshotJob(42, "old", recognize, completed))
        assert started.wait(3)
        assert worker.submit(ScreenshotJob(42, "old", skipped, completed))
        worker.cancel("old")
        assert worker.submit(ScreenshotJob(42, "new", lambda: "new", completed))
        release.set()
        dispatched.get(timeout=3)()
        completed.assert_called_once_with("new", None)
        skipped.assert_not_called()
    finally:
        release.set()
        worker.stop()


def test_cancel_also_discards_a_result_already_in_telegram_queue():
    dispatched = Queue()
    completed = Mock()
    worker = ScreenshotWorker(dispatched.put)
    try:
        assert worker.submit(ScreenshotJob(42, "old", lambda: {}, completed))
        apply_result = dispatched.get(timeout=3)
        worker.cancel("old")
        apply_result()
        completed.assert_not_called()
    finally:
        worker.stop()


def test_worker_survives_an_unexpected_error_without_exposing_exception_text(caplog):
    dispatched = Queue()
    completed = Mock()

    def fail():
        raise RuntimeError("private-file-url")

    worker = ScreenshotWorker(dispatched.put)
    try:
        assert worker.submit(ScreenshotJob(42, "session", fail, completed))
        dispatched.get(timeout=3)()
        completed.assert_called_once_with(None, "RuntimeError")
        assert worker.submit(ScreenshotJob(42, "session", lambda: {}, completed))
        dispatched.get(timeout=3)()
        assert completed.call_count == 2
        assert "private-file-url" not in caplog.text
    finally:
        worker.stop()


def test_stop_discards_results_and_rejects_new_work():
    dispatched = Queue()
    completed = Mock()
    worker = ScreenshotWorker(dispatched.put)
    assert worker.submit(ScreenshotJob(42, "session", lambda: {}, completed))
    apply_result = dispatched.get(timeout=3)
    worker.stop()
    apply_result()
    completed.assert_not_called()
    assert not worker.submit(ScreenshotJob(42, "session", lambda: {}, completed))


@pytest.mark.parametrize("after_dispatch", [False, True])
def test_cancel_cleans_result_without_applying_it(after_dispatch):
    dispatched = Queue()
    started, release, cleaned = Event(), Event(), Event()
    complete, discard = Mock(), Mock(side_effect=lambda *_: cleaned.set())

    def recognize():
        started.set()
        assert release.wait(3)
        return "stored image"

    worker = ScreenshotWorker(dispatched.put)
    try:
        assert worker.submit(ScreenshotJob(42, "session", recognize, complete, discard))
        assert started.wait(3)
        if after_dispatch:
            release.set()
            apply = dispatched.get(timeout=3)
        worker.cancel("session")
        release.set()
        if after_dispatch:
            apply()
        assert cleaned.wait(3)
        discard.assert_called_once_with("stored image", None)
        complete.assert_not_called()
    finally:
        release.set()
        worker.stop()


def test_ocr_metrics_separate_queue_wait_from_time_until_result_is_applied():
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    dispatched = Queue()
    started, release = Event(), Event()
    now = [10.0]

    def recognize():
        started.set()
        assert release.wait(3)
        return "image"

    def complete(*_):
        now[0] += 2  # Result application and Telegram message editing.

    worker = ScreenshotWorker(dispatched.put, metrics=metrics, clock=lambda: now[0])
    try:
        assert worker.submit(ScreenshotJob(42, "session", recognize, complete))
        assert started.wait(3)
        now[0] = 12.0
        assert worker.submit(ScreenshotJob(42, "session", lambda: "second", complete))
        assert registry.get_sample_value("srm_screenshot_queue_size") == 1
        now[0] = 17.0
        release.set()
        first, second = dispatched.get(timeout=3), dispatched.get(timeout=3)
        assert registry.get_sample_value("srm_screenshot_queue_size") == 0
        assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_sum", {"stage": "queue"}) == 5
        assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_count", {"stage": "total"}) == 0
        now[0] = 20.0
        first()
        second()
        assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_count", {"stage": "total"}) == 2
        assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_sum", {"stage": "total"}) == 24
    finally:
        release.set()
        worker.stop()


def test_cancel_and_stop_clear_queue_gauge_without_counting_skipped_jobs():
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    started, release = Event(), Event()

    def recognize():
        started.set()
        assert release.wait(3)

    worker = ScreenshotWorker(Mock(), per_user=2, total=2, metrics=metrics)
    try:
        assert worker.submit(ScreenshotJob(42, "active", recognize, Mock()))
        assert started.wait(3)
        assert worker.submit(ScreenshotJob(42, "queued", Mock(), Mock()))
        assert not worker.submit(ScreenshotJob(42, "rejected", Mock(), Mock()))
        assert registry.get_sample_value("srm_screenshot_queue_size") == 1
        worker.cancel("queued")
        assert registry.get_sample_value("srm_screenshot_queue_size") == 0
        assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_count", {"stage": "queue"}) == 1
        assert worker.submit(ScreenshotJob(42, "queued", Mock(), Mock()))
        release.set()
    finally:
        release.set()
        worker.stop()
    assert registry.get_sample_value("srm_screenshot_queue_size") == 0
