from __future__ import annotations

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


METRICS_LISTEN = "0.0.0.0"
METRICS_PORT = 9100
_STARTED_AT_KEY = "srm_metrics_started_at"


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
