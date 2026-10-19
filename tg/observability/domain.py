from contextlib import contextmanager
from time import monotonic, time
from typing import Callable, Iterator

from tg.observability.definitions import APPLICATION_METRICS, ApplicationMetrics


def record_resource_update(
    category: str,
    field: str,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
    wall_clock: Callable[[], float] = time,
    *,
    source: str = "manual",
) -> None:
    labels = {"category": category, "field": field}
    metrics.resource_updates.labels(**labels).inc()
    metrics.resource_inputs.labels(category=category, source=source).inc()
    metrics.last_resource_update_timestamp.labels(**labels).set(wall_clock())


def record_screenshot_processed(
    result: str,
    metrics: ApplicationMetrics = APPLICATION_METRICS,
) -> None:
    metrics.screenshots_processed.labels(result=result).inc()


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
