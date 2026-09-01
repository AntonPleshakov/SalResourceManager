from time import monotonic, time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from telebot.handler_backends import BaseMiddleware

from tg.observability.definitions import (
    APPLICATION_METRICS,
    HANDLER_ACTION_KEY,
    ApplicationMetrics,
)
from tg.observability.updates import Update, chat_type, event_type


STARTED_AT_KEY = "srm_metrics_started_at"


def _finish_webhook_request(
    middleware,
    request: Request,
    method: str,
    status_code: int,
    started_at: float,
) -> None:
    middleware._metrics.requests.labels(
        method=method,
        status_code=str(status_code),
    ).inc()
    middleware._metrics.request_duration.labels(method=method).observe(
        max(0.0, middleware._clock() - started_at)
    )
    content_length = request.headers.get("content-length", "")
    if content_length.isdecimal():
        middleware._metrics.request_size.labels(method=method).observe(
            int(content_length)
        )
    middleware._metrics.last_request_timestamp.set(middleware._wall_clock())
    middleware._metrics.requests_in_progress.labels(method=method).dec()


async def _record_webhook_request(
    middleware,
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    started_at = middleware._clock()
    method = request.method.lower()
    middleware._metrics.requests_in_progress.labels(method=method).inc()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _finish_webhook_request(
            middleware, request, method, status_code, started_at
        )


def _finish_started_event(middleware, update: Update, data: dict) -> tuple[str, float]:
    started = data.pop(STARTED_AT_KEY, None)
    if started is None:
        return event_type(update), middleware._clock()
    update_type, started_at = started
    middleware._metrics.events_in_progress.labels(event_type=update_type).dec()
    return update_type, started_at


def _record_telegram_outcome(
    middleware,
    update: Update,
    data: dict,
    exception: BaseException | None,
    update_type: str,
) -> None:
    if exception is not None:
        outcome = "failed"
    elif data.get(HANDLER_ACTION_KEY) is not None:
        outcome = "handled"
    else:
        outcome = "ignored"
    middleware._metrics.event_outcomes.labels(
        event_type=update_type,
        chat_type=chat_type(update),
        outcome=outcome,
    ).inc()
    middleware._metrics.last_event_timestamp.labels(event_type=update_type).set(
        middleware._wall_clock()
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
        return await _record_webhook_request(self, request, call_next)


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

    def pre_process(self, update: Update, data: dict) -> None:
        update_type = event_type(update)
        data[STARTED_AT_KEY] = (update_type, self._clock())
        self._metrics.events.labels(event_type=update_type).inc()
        self._metrics.events_in_progress.labels(event_type=update_type).inc()

    def post_process(
        self,
        update: Update,
        data: dict,
        exception: BaseException | None,
    ) -> None:
        update_type, started_at = _finish_started_event(self, update, data)
        self._metrics.event_duration.labels(event_type=update_type).observe(
            max(0.0, self._clock() - started_at)
        )
        if exception is not None:
            self._metrics.event_errors.labels(event_type=update_type).inc()
        _record_telegram_outcome(self, update, data, exception, update_type)
