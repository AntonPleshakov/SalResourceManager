from queue import Queue
from threading import Event, get_ident
from unittest.mock import Mock

from tg.user_data.screenshot_jobs import ScreenshotJob, ScreenshotWorker


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
