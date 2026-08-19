import asyncio
from unittest.mock import Mock
from urllib.request import urlopen

import pytest
from prometheus_client import CollectorRegistry
from starlette.requests import Request
from starlette.responses import Response
from telebot.types import CallbackQuery, Chat, Message, User

from tg.metrics import (
    ApplicationMetrics,
    instrument_registered_handlers,
    observe_score_calculation,
    record_resource_update,
    register_player_account_metrics,
    start_metrics_server,
    TelegramMetricsMiddleware,
    WebhookMetricsMiddleware,
)


def make_message() -> Message:
    user = User(42, False, "Tester", username="tester")
    return Message(1, user, 0, Chat(42, "private"), "text", {}, None)


def make_callback_query() -> CallbackQuery:
    message = make_message()
    return CallbackQuery(
        "callback-1",
        message.from_user,
        "resources",
        "",
        None,
        message,
    )


def make_request(
    path: str = "/telegram/", content_length: int | None = None
) -> Request:
    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("localhost", 8443),
        }
    )


async def empty_app(scope, receive, send) -> None:
    pass


def test_webhook_middleware_records_http_request() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((5.0, 5.2))
    middleware = WebhookMetricsMiddleware(
        empty_app,
        webhook_path="/telegram/",
        metrics=metrics,
        clock=lambda: next(timestamps),
        wall_clock=lambda: 100.0,
    )

    async def call_next(request: Request) -> Response:
        return Response(status_code=403)

    response = asyncio.run(
        middleware.dispatch(make_request(content_length=768), call_next)
    )

    assert response.status_code == 403
    assert registry.get_sample_value(
        "srm_requests_total",
        {"method": "post", "status_code": "403"},
    ) == 1
    assert registry.get_sample_value(
        "srm_request_duration_seconds_sum",
        {"method": "post"},
    ) == pytest.approx(0.2)
    assert registry.get_sample_value(
        "srm_request_size_bytes_sum",
        {"method": "post"},
    ) == 768
    assert registry.get_sample_value(
        "srm_requests_in_progress",
        {"method": "post"},
    ) == 0
    assert registry.get_sample_value("srm_last_request_timestamp_seconds") == 100


def test_webhook_middleware_ignores_other_paths() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    middleware = WebhookMetricsMiddleware(
        empty_app,
        webhook_path="/telegram/",
        metrics=metrics,
    )

    async def call_next(request: Request) -> Response:
        return Response(status_code=404)

    asyncio.run(middleware.dispatch(make_request("/other"), call_next))

    assert registry.get_sample_value("srm_requests_total") is None


def test_middleware_records_successful_message() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((10.0, 10.25))
    middleware = TelegramMetricsMiddleware(
        metrics,
        lambda: next(timestamps),
        lambda: 200.0,
    )
    data = {}
    message = make_message()

    middleware.pre_process(message, data)
    middleware.post_process(message, data, None)

    assert registry.get_sample_value(
        "srm_events_total",
        {"event_type": "message"},
    ) == 1
    assert registry.get_sample_value(
        "srm_event_duration_seconds_sum",
        {"event_type": "message"},
    ) == 0.25
    assert registry.get_sample_value(
        "srm_event_errors_total",
        {"event_type": "message"},
    ) is None
    assert registry.get_sample_value(
        "srm_events_in_progress",
        {"event_type": "message"},
    ) == 0
    assert registry.get_sample_value(
        "srm_last_event_timestamp_seconds",
        {"event_type": "message"},
    ) == 200
    assert registry.get_sample_value(
        "srm_event_outcomes_total",
        {
            "event_type": "message",
            "chat_type": "private",
            "outcome": "ignored",
        },
    ) == 1


def test_middleware_records_failed_callback_query() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((20.0, 20.5))
    middleware = TelegramMetricsMiddleware(metrics, lambda: next(timestamps))
    data = {}
    callback_query = make_callback_query()

    middleware.pre_process(callback_query, data)
    middleware.post_process(callback_query, data, RuntimeError("failed"))

    labels = {"event_type": "callback_query"}
    assert registry.get_sample_value("srm_events_total", labels) == 1
    assert registry.get_sample_value("srm_event_errors_total", labels) == 1
    assert registry.get_sample_value(
        "srm_event_duration_seconds_sum", labels
    ) == 0.5


def test_registered_handler_metrics_include_action_duration_and_log(
    monkeypatch,
) -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((10.0, 11.25))
    calls = []

    def handled_message(message: Message, bot) -> None:
        calls.append((message, bot))

    class FakeBot:
        message_handlers = [
            {"function": handled_message, "pass_bot": True}
        ]
        callback_query_handlers = []

    bot = FakeBot()
    log_info = Mock()
    monkeypatch.setattr("tg.metrics.logger.info", log_info)
    instrument_registered_handlers(
        bot,
        metrics,
        clock=lambda: next(timestamps),
    )
    data = {}
    message = make_message()

    bot.message_handlers[0]["function"](message, data, bot)

    action = f"{__name__}.handled_message"
    labels = {"event_type": "message", "handler": action}
    assert calls == [(message, bot)]
    assert registry.get_sample_value(
        "srm_handler_calls_total", {**labels, "result": "completed"}
    ) == 1
    assert registry.get_sample_value(
        "srm_handler_duration_seconds_sum", labels
    ) == pytest.approx(1.25)
    assert registry.get_sample_value(
        "srm_handler_duration_seconds_count", labels
    ) == 1
    assert registry.get_sample_value(
        "srm_handler_duration_seconds_bucket", {**labels, "le": "1.0"}
    ) == 0
    assert registry.get_sample_value("srm_handlers_in_progress", labels) == 0
    log_info.assert_called_once_with(
        "Telegram handler finished event_type=%s handler=%s "
        "result=%s duration_seconds=%.3f user_id=%s chat_id=%s "
        "update_id=%s error_type=%s",
        "message",
        action,
        "completed",
        1.25,
        42,
        42,
        1,
        "none",
    )


def test_failed_callback_handler_logs_result_and_exception(monkeypatch) -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((20.0, 20.5))

    def failed_callback(callback_query: CallbackQuery) -> None:
        raise RuntimeError("failed")

    class FakeBot:
        message_handlers = []
        callback_query_handlers = [{"function": failed_callback}]

    bot = FakeBot()
    log_info = Mock()
    monkeypatch.setattr("tg.metrics.logger.info", log_info)
    instrument_registered_handlers(
        bot,
        metrics,
        clock=lambda: next(timestamps),
    )

    with pytest.raises(RuntimeError, match="failed"):
        bot.callback_query_handlers[0]["function"](
            make_callback_query(), {}, bot
        )

    action = f"{__name__}.failed_callback"
    log_info.assert_called_once_with(
        "Telegram handler finished event_type=%s handler=%s "
        "result=%s duration_seconds=%.3f user_id=%s chat_id=%s "
        "update_id=%s error_type=%s",
        "callback_query",
        action,
        "failed",
        0.5,
        42,
        42,
        "callback-1",
        "RuntimeError",
    )


def test_ready_metric_can_follow_application_lifecycle() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)

    metrics.ready.set(1)
    assert registry.get_sample_value("srm_ready") == 1

    metrics.ready.set(0)
    assert registry.get_sample_value("srm_ready") == 0


def test_resource_updates_record_category_field_and_timestamp() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)

    record_resource_update(
        "resources",
        "hammers",
        metrics,
        wall_clock=lambda: 300.0,
    )

    labels = {"category": "resources", "field": "hammers"}
    assert registry.get_sample_value("srm_resource_updates_total", labels) == 1
    assert registry.get_sample_value(
        "srm_last_resource_update_timestamp_seconds", labels
    ) == 300


def test_score_calculations_record_result_and_duration() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    timestamps = iter((10.0, 10.25, 20.0, 20.5))

    with observe_score_calculation(
        "personal_summary", metrics, lambda: next(timestamps)
    ):
        pass
    with pytest.raises(RuntimeError):
        with observe_score_calculation(
            "public", metrics, lambda: next(timestamps)
        ):
            raise RuntimeError("failed")

    assert registry.get_sample_value(
        "srm_score_calculations_total",
        {"scope": "personal_summary", "result": "completed"},
    ) == 1
    assert registry.get_sample_value(
        "srm_score_calculations_total",
        {"scope": "public", "result": "failed"},
    ) == 1
    assert registry.get_sample_value(
        "srm_score_calculation_duration_seconds_sum",
        {"scope": "personal_summary"},
    ) == 0.25


def test_player_account_metrics_are_calculated_at_scrape_time() -> None:
    registry = CollectorRegistry()
    account_counts = [1, 2, 2, 4]
    register_player_account_metrics(lambda: account_counts, registry)

    assert registry.get_sample_value("srm_users") == 4
    assert registry.get_sample_value("srm_accounts") == 9
    assert registry.get_sample_value(
        "srm_users_by_account_count", {"account_count": "1"}
    ) == 1
    assert registry.get_sample_value(
        "srm_users_by_account_count", {"account_count": "2"}
    ) == 2
    assert registry.get_sample_value(
        "srm_users_by_account_count", {"account_count": "4"}
    ) == 1

    account_counts[:] = [1, 1]
    assert registry.get_sample_value("srm_users") == 2
    assert registry.get_sample_value("srm_accounts") == 2
    assert registry.get_sample_value(
        "srm_users_by_account_count", {"account_count": "1"}
    ) == 2


def test_metrics_server_exposes_prometheus_text_format() -> None:
    metrics_server = start_metrics_server(port=0, listen="127.0.0.1")
    try:
        port = metrics_server.server.server_port
        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
            body = response.read().decode()
        assert response.status == 200
        assert "srm_ready" in body
        assert "python_info" in body
    finally:
        metrics_server.stop()
