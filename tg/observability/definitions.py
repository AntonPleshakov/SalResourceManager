from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, REGISTRY


METRICS_LISTEN = "0.0.0.0"
METRICS_PORT = 9100
HANDLER_ACTION_KEY = "srm_metrics_handler_action"

HTTP_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
HANDLER_DURATION_BUCKETS = (
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
)


def _counter(
    registry: CollectorRegistry,
    name: str,
    description: str,
    labels: tuple[str, ...] = (),
) -> Counter:
    return Counter(name, description, labels, registry=registry)


def _gauge(
    registry: CollectorRegistry,
    name: str,
    description: str,
    labels: tuple[str, ...] = (),
) -> Gauge:
    return Gauge(name, description, labels, registry=registry)


def _histogram(
    registry: CollectorRegistry,
    name: str,
    description: str,
    labels: tuple[str, ...],
    buckets: tuple[float, ...],
) -> Histogram:
    return Histogram(name, description, labels, buckets=buckets, registry=registry)


class ApplicationMetrics:
    def _create_http_metrics(self, registry: CollectorRegistry) -> None:
        self.ready = _gauge(
            registry,
            "srm_ready",
            "Whether the bot completed startup and is ready to process updates.",
        )
        self.requests = _counter(
            registry,
            "srm_requests_total",
            "HTTP requests received by the Telegram webhook.",
            ("method", "status_code"),
        )
        self.request_duration = _histogram(
            registry,
            "srm_request_duration_seconds",
            "Time spent serving HTTP requests to the Telegram webhook.",
            ("method",),
            HTTP_DURATION_BUCKETS,
        )
        self.request_size = _histogram(
            registry,
            "srm_request_size_bytes",
            "Size of HTTP request bodies received by the Telegram webhook.",
            ("method",),
            (128, 256, 512, 1024, 2048, 4096, 8192, 16384, 65536),
        )
        self.requests_in_progress = _gauge(
            registry,
            "srm_requests_in_progress",
            "HTTP requests currently being served by the Telegram webhook.",
            ("method",),
        )
        self.last_request_timestamp = _gauge(
            registry,
            "srm_last_request_timestamp_seconds",
            "Unix timestamp of the last Telegram webhook request.",
        )

    def _create_telegram_metrics(self, registry: CollectorRegistry) -> None:
        self.events = _counter(
            registry,
            "srm_events_total",
            "Authorized Telegram events processed by the bot.",
            ("event_type",),
        )
        self.event_errors = _counter(
            registry,
            "srm_event_errors_total",
            "Telegram events that finished with an unhandled error.",
            ("event_type",),
        )
        self.event_outcomes = _counter(
            registry,
            "srm_event_outcomes_total",
            "Authorized Telegram updates grouped by whether a bot handler ran.",
            ("event_type", "chat_type", "outcome"),
        )
        self.event_duration = _histogram(
            registry,
            "srm_event_duration_seconds",
            "Time spent processing Telegram events.",
            ("event_type",),
            HTTP_DURATION_BUCKETS,
        )
        self.events_in_progress = _gauge(
            registry,
            "srm_events_in_progress",
            "Telegram events currently being processed by bot handlers.",
            ("event_type",),
        )
        self.last_event_timestamp = _gauge(
            registry,
            "srm_last_event_timestamp_seconds",
            "Unix timestamp of the last processed Telegram event.",
            ("event_type",),
        )
        self.handler_calls = _counter(
            registry,
            "srm_handler_calls_total",
            "Telegram bot handler calls grouped by handler and result.",
            ("event_type", "handler", "result"),
        )
        self.handler_duration = _histogram(
            registry,
            "srm_handler_duration_seconds",
            "Time spent inside a matched Telegram bot handler.",
            ("event_type", "handler"),
            HANDLER_DURATION_BUCKETS,
        )
        self.handlers_in_progress = _gauge(
            registry,
            "srm_handlers_in_progress",
            "Telegram bot handlers currently running.",
            ("event_type", "handler"),
        )
        self.access_checks = _counter(
            registry,
            "srm_access_checks_total",
            "Bot access decisions.",
            ("result",),
        )

    def _create_domain_metrics(self, registry: CollectorRegistry) -> None:
        self.reminders = _counter(
            registry,
            "srm_reminders_total",
            "Resource reminder delivery outcomes by recipient.",
            ("kind", "result"),
        )
        self.reminder_runs = _counter(
            registry,
            "srm_reminder_runs_total",
            "Resource reminder job outcomes.",
            ("kind", "result"),
        )
        self.next_reminder_timestamp = _gauge(
            registry,
            "srm_next_reminder_timestamp_seconds",
            "Unix timestamp of the next scheduled resource reminder.",
            ("kind",),
        )
        self.reports = _counter(
            registry,
            "srm_reports_total",
            "Report export outcomes.",
            ("report", "result"),
        )
        self.report_duration = _histogram(
            registry,
            "srm_report_duration_seconds",
            "Time spent exporting reports.",
            ("report",),
            (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
        )
        self.resource_updates = _counter(
            registry,
            "srm_resource_updates_total",
            "Successful player resource updates.",
            ("category", "field"),
        )
        self.last_resource_update_timestamp = _gauge(
            registry,
            "srm_last_resource_update_timestamp_seconds",
            "Unix timestamp of the last successful player resource update.",
            ("category", "field"),
        )
        self.score_calculations = _counter(
            registry,
            "srm_score_calculations_total",
            "War score calculation outcomes.",
            ("scope", "result"),
        )
        self.score_calculation_duration = _histogram(
            registry,
            "srm_score_calculation_duration_seconds",
            "Time spent calculating war scores.",
            ("scope",),
            HANDLER_DURATION_BUCKETS[:10],
        )

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self._create_http_metrics(registry)
        self._create_telegram_metrics(registry)
        self._create_domain_metrics(registry)


APPLICATION_METRICS = ApplicationMetrics()
