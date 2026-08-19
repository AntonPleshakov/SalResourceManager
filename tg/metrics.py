from __future__ import annotations

import inspect
from collections import Counter as ValueCounter
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Thread
from time import monotonic, time
from typing import Callable, Iterable, Iterator

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, REGISTRY
from prometheus_client.core import GaugeMetricFamily
from prometheus_client import start_http_server
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from telebot.handler_backends import BaseMiddleware
from telebot.types import CallbackQuery, Message

from logger.app_logger import logger


METRICS_LISTEN = "0.0.0.0"
METRICS_PORT = 9100
_STARTED_AT_KEY = "srm_metrics_started_at"
_HANDLER_ACTION_KEY = "srm_metrics_handler_action"


class ApplicationMetrics:
    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.ready = Gauge(
            "srm_ready",
            "Whether the bot completed startup and is ready to process updates.",
            registry=registry,
        )
        self.requests = Counter(
            "srm_requests_total",
            "HTTP requests received by the Telegram webhook.",
            ("method", "status_code"),
            registry=registry,
        )
        self.request_duration = Histogram(
            "srm_request_duration_seconds",
            "Time spent serving HTTP requests to the Telegram webhook.",
            ("method",),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=registry,
        )
        self.request_size = Histogram(
            "srm_request_size_bytes",
            "Size of HTTP request bodies received by the Telegram webhook.",
            ("method",),
            buckets=(128, 256, 512, 1024, 2048, 4096, 8192, 16384, 65536),
            registry=registry,
        )
        self.requests_in_progress = Gauge(
            "srm_requests_in_progress",
            "HTTP requests currently being served by the Telegram webhook.",
            ("method",),
            registry=registry,
        )
        self.last_request_timestamp = Gauge(
            "srm_last_request_timestamp_seconds",
            "Unix timestamp of the last Telegram webhook request.",
            registry=registry,
        )
        self.events = Counter(
            "srm_events_total",
            "Authorized Telegram events processed by the bot.",
            ("event_type",),
            registry=registry,
        )
        self.event_errors = Counter(
            "srm_event_errors_total",
            "Telegram events that finished with an unhandled error.",
            ("event_type",),
            registry=registry,
        )
        self.event_outcomes = Counter(
            "srm_event_outcomes_total",
            "Authorized Telegram updates grouped by whether a bot handler ran.",
            ("event_type", "chat_type", "outcome"),
            registry=registry,
        )
        self.event_duration = Histogram(
            "srm_event_duration_seconds",
            "Time spent processing Telegram events.",
            ("event_type",),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=registry,
        )
        self.events_in_progress = Gauge(
            "srm_events_in_progress",
            "Telegram events currently being processed by bot handlers.",
            ("event_type",),
            registry=registry,
        )
        self.last_event_timestamp = Gauge(
            "srm_last_event_timestamp_seconds",
            "Unix timestamp of the last processed Telegram event.",
            ("event_type",),
            registry=registry,
        )
        self.handler_calls = Counter(
            "srm_handler_calls_total",
            "Telegram bot handler calls grouped by handler and result.",
            ("event_type", "handler", "result"),
            registry=registry,
        )
        self.handler_duration = Histogram(
            "srm_handler_duration_seconds",
            "Time spent inside a matched Telegram bot handler.",
            ("event_type", "handler"),
            buckets=(
                0.001,
                0.0025,
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1,
                2.5,
                5,
                10,
                30,
            ),
            registry=registry,
        )
        self.handlers_in_progress = Gauge(
            "srm_handlers_in_progress",
            "Telegram bot handlers currently running.",
            ("event_type", "handler"),
            registry=registry,
        )
        self.access_checks = Counter(
            "srm_access_checks_total",
            "Bot access decisions.",
            ("result",),
            registry=registry,
        )
        self.reminders = Counter(
            "srm_reminders_total",
            "Resource reminder delivery outcomes by recipient.",
            ("kind", "result"),
            registry=registry,
        )
        self.reminder_runs = Counter(
            "srm_reminder_runs_total",
            "Resource reminder job outcomes.",
            ("kind", "result"),
            registry=registry,
        )
        self.next_reminder_timestamp = Gauge(
            "srm_next_reminder_timestamp_seconds",
            "Unix timestamp of the next scheduled resource reminder.",
            ("kind",),
            registry=registry,
        )
        self.reports = Counter(
            "srm_reports_total",
            "Report export outcomes.",
            ("report", "result"),
            registry=registry,
        )
        self.report_duration = Histogram(
            "srm_report_duration_seconds",
            "Time spent exporting reports.",
            ("report",),
            buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
            registry=registry,
        )
        self.resource_updates = Counter(
            "srm_resource_updates_total",
            "Successful player resource updates.",
            ("category", "field"),
            registry=registry,
        )
        self.last_resource_update_timestamp = Gauge(
            "srm_last_resource_update_timestamp_seconds",
            "Unix timestamp of the last successful player resource update.",
            ("category", "field"),
            registry=registry,
        )
        self.score_calculations = Counter(
            "srm_score_calculations_total",
            "War score calculation outcomes.",
            ("scope", "result"),
            registry=registry,
        )
        self.score_calculation_duration = Histogram(
            "srm_score_calculation_duration_seconds",
            "Time spent calculating war scores.",
            ("scope",),
            buckets=(
                0.001,
                0.0025,
                0.005,
                0.01,
                0.025,
                0.05,
                0.1,
                0.25,
                0.5,
                1,
            ),
            registry=registry,
        )


APPLICATION_METRICS = ApplicationMetrics()


class PlayerAccountCollector:
    def __init__(self, account_counts: Callable[[], Iterable[int]]) -> None:
        self._account_counts = account_counts

    def collect(self):
        account_counts = list(self._account_counts())
        users = GaugeMetricFamily(
            "srm_users",
            "Number of Telegram users with at least one game account.",
        )
        users.add_metric([], len(account_counts))
        yield users

        accounts = GaugeMetricFamily(
            "srm_accounts",
            "Number of game accounts.",
        )
        accounts.add_metric([], sum(account_counts))
        yield accounts

        distribution = GaugeMetricFamily(
            "srm_users_by_account_count",
            "Number of Telegram users grouped by their game account count.",
            labels=("account_count",),
        )
        for account_count, user_count in sorted(
            ValueCounter(account_counts).items()
        ):
            distribution.add_metric([str(account_count)], user_count)
        yield distribution


def register_player_account_metrics(
    account_counts: Callable[[], Iterable[int]],
    registry: CollectorRegistry = REGISTRY,
) -> PlayerAccountCollector:
    collector = PlayerAccountCollector(account_counts)
    registry.register(collector)
    return collector


def record_resource_update(
    category: str,
    field: str,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
    wall_clock: Callable[[], float] = time,
) -> None:
    labels = {"category": category, "field": field}
    metrics.resource_updates.labels(**labels).inc()
    metrics.last_resource_update_timestamp.labels(**labels).set(wall_clock())


@contextmanager
def observe_score_calculation(
    scope: str,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
    clock: Callable[[], float] = monotonic,
) -> Iterator[None]:
    started_at = clock()
    result = "failed"
    try:
        yield
    except BaseException:
        raise
    else:
        result = "completed"
    finally:
        metrics.score_calculations.labels(scope=scope, result=result).inc()
        metrics.score_calculation_duration.labels(scope=scope).observe(
            max(0.0, clock() - started_at)
        )


def _event_type(update: Message | CallbackQuery) -> str:
    return "callback_query" if isinstance(update, CallbackQuery) else "message"


def _chat_type(update: Message | CallbackQuery) -> str:
    message = update.message if isinstance(update, CallbackQuery) else update
    return str(getattr(getattr(message, "chat", None), "type", "unknown"))


def _handler_action(handler: Callable) -> str:
    module = str(getattr(handler, "__module__", "") or "")
    if module.startswith("tg."):
        module = module[3:]
    elif module == "__main__":
        module = "main"
    name = str(getattr(handler, "__name__", handler.__class__.__name__))
    return f"{module}.{name}" if module else name


def _update_log_context(
    update: Message | CallbackQuery,
) -> tuple[object, object, object]:
    message = update.message if isinstance(update, CallbackQuery) else update
    user_id = getattr(getattr(update, "from_user", None), "id", None)
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    update_id = (
        getattr(update, "id", None)
        if isinstance(update, CallbackQuery)
        else getattr(message, "id", None)
    )
    return user_id, chat_id, update_id


def _instrument_handler(
    handler: Callable,
    *,
    pass_bot: bool,
    event_type: str,
    metrics: ApplicationMetrics,
    clock: Callable[[], float],
) -> Callable:
    action = _handler_action(handler)
    parameters = inspect.signature(handler).parameters

    def instrumented(update, data: dict, bot):
        data[_HANDLER_ACTION_KEY] = action
        started_at = clock()
        metrics.handlers_in_progress.labels(
            event_type=event_type,
            handler=action,
        ).inc()
        result = "failed"
        error_type = "none"
        try:
            kwargs = {
                name: data[name]
                for name in parameters
                if name in data and name not in {"data", "bot"}
            }
            if "data" in parameters:
                kwargs["data"] = data
            if pass_bot or "bot" in parameters:
                kwargs["bot"] = bot
            handler_result = handler(update, **kwargs)
            result = "completed"
            return handler_result
        except BaseException as error:
            error_type = type(error).__name__
            raise
        finally:
            duration = max(0.0, clock() - started_at)
            labels = {"event_type": event_type, "handler": action}
            metrics.handlers_in_progress.labels(**labels).dec()
            metrics.handler_calls.labels(**labels, result=result).inc()
            metrics.handler_duration.labels(**labels).observe(duration)
            user_id, chat_id, update_id = _update_log_context(update)
            logger.info(
                "Telegram handler finished event_type=%s handler=%s "
                "result=%s duration_seconds=%.3f user_id=%s chat_id=%s "
                "update_id=%s error_type=%s",
                event_type,
                action,
                result,
                duration,
                user_id,
                chat_id,
                update_id,
                error_type,
            )

    instrumented.__name__ = (
        f"instrumented_{getattr(handler, '__name__', 'handler')}"
    )
    instrumented.__module__ = getattr(handler, "__module__", __name__)
    setattr(instrumented, "_srm_instrumented", True)
    return instrumented


def instrument_registered_handlers(
    bot,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
    clock: Callable[[], float] = monotonic,
) -> None:
    """Wrap the bot's finite handler set with low-cardinality metrics."""
    handler_groups = (
        ("message", bot.message_handlers),
        ("callback_query", bot.callback_query_handlers),
    )
    for event_type, handlers in handler_groups:
        for definition in handlers:
            handler = definition["function"]
            if getattr(handler, "_srm_instrumented", False):
                continue
            definition["function"] = _instrument_handler(
                handler,
                pass_bot=bool(definition.get("pass_bot")),
                event_type=event_type,
                metrics=metrics,
                clock=clock,
            )


class WebhookMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        webhook_path: str,
        metrics: ApplicationMetrics = APPLICATION_METRICS,
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time,
    ) -> None:
        super().__init__(app)
        self._webhook_path = webhook_path
        self._metrics = metrics
        self._clock = clock
        self._wall_clock = wall_clock

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path != self._webhook_path:
            return await call_next(request)

        started_at = self._clock()
        method = request.method.lower()
        self._metrics.requests_in_progress.labels(method=method).inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            self._metrics.requests.labels(
                method=method,
                status_code=str(status_code),
            ).inc()
            self._metrics.request_duration.labels(method=method).observe(
                max(0.0, self._clock() - started_at)
            )
            content_length = request.headers.get("content-length", "")
            if content_length.isdecimal():
                self._metrics.request_size.labels(method=method).observe(
                    int(content_length)
                )
            self._metrics.last_request_timestamp.set(self._wall_clock())
            self._metrics.requests_in_progress.labels(method=method).dec()


class TelegramMetricsMiddleware(BaseMiddleware):
    def __init__(
        self,
        metrics: ApplicationMetrics = APPLICATION_METRICS,
        clock: Callable[[], float] = monotonic,
        wall_clock: Callable[[], float] = time,
    ) -> None:
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._metrics = metrics
        self._clock = clock
        self._wall_clock = wall_clock

    def pre_process(
        self, update: Message | CallbackQuery, data: dict
    ) -> None:
        event_type = _event_type(update)
        data[_STARTED_AT_KEY] = (event_type, self._clock())
        self._metrics.events.labels(event_type=event_type).inc()
        self._metrics.events_in_progress.labels(event_type=event_type).inc()
        return None

    def post_process(
        self,
        update: Message | CallbackQuery,
        data: dict,
        exception: BaseException | None,
    ) -> None:
        started = data.pop(_STARTED_AT_KEY, None)
        if started is None:
            event_type, started_at = _event_type(update), self._clock()
        else:
            event_type, started_at = started
            self._metrics.events_in_progress.labels(event_type=event_type).dec()
        duration = max(0.0, self._clock() - started_at)
        self._metrics.event_duration.labels(event_type=event_type).observe(
            duration
        )
        if exception is not None:
            self._metrics.event_errors.labels(event_type=event_type).inc()
        action = data.get(_HANDLER_ACTION_KEY)
        outcome = (
            "failed"
            if exception is not None
            else "handled"
            if action is not None
            else "ignored"
        )
        self._metrics.event_outcomes.labels(
            event_type=event_type,
            chat_type=_chat_type(update),
            outcome=outcome,
        ).inc()
        self._metrics.last_event_timestamp.labels(event_type=event_type).set(
            self._wall_clock()
        )


@dataclass(frozen=True)
class MetricsServer:
    server: object
    thread: Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def start_metrics_server(
    port: int = METRICS_PORT,
    listen: str = METRICS_LISTEN,
) -> MetricsServer:
    server, thread = start_http_server(port=port, addr=listen)
    return MetricsServer(server, thread)
