import inspect
from time import monotonic
from typing import Callable, Mapping

from logger.app_logger import logger
from tg.observability.definitions import (
    APPLICATION_METRICS,
    HANDLER_ACTION_KEY,
    ApplicationMetrics,
)
from tg.observability.updates import log_context


def _handler_action(handler: Callable) -> str:
    module = str(getattr(handler, "__module__", "") or "")
    if module.startswith("tg."):
        module = module[3:]
    elif module == "__main__":
        module = "main"
    name = str(getattr(handler, "__name__", handler.__class__.__name__))
    return f"{module}.{name}" if module else name


def _handler_kwargs(
    parameters: Mapping[str, inspect.Parameter],
    data: dict,
    bot,
    pass_bot: bool,
) -> dict:
    kwargs = {
        name: data[name]
        for name in parameters
        if name in data and name not in {"data", "bot"}
    }
    if "data" in parameters:
        kwargs["data"] = data
    if pass_bot or "bot" in parameters:
        kwargs["bot"] = bot
    return kwargs


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
        data[HANDLER_ACTION_KEY] = action
        started_at = clock()
        labels = {"event_type": event_type, "handler": action}
        metrics.handlers_in_progress.labels(**labels).inc()
        result = "failed"
        error_type = "none"
        try:
            handler_result = handler(
                update,
                **_handler_kwargs(parameters, data, bot, pass_bot),
            )
            result = "completed"
            return handler_result
        except BaseException as error:
            error_type = type(error).__name__
            raise
        finally:
            duration = max(0.0, clock() - started_at)
            metrics.handlers_in_progress.labels(**labels).dec()
            metrics.handler_calls.labels(**labels, result=result).inc()
            metrics.handler_duration.labels(**labels).observe(duration)
            user_id, chat_id, update_id = log_context(update)
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
