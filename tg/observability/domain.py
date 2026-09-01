from contextlib import contextmanager
from time import monotonic, time
from typing import Callable, Iterator

from tg.observability.definitions import APPLICATION_METRICS, ApplicationMetrics


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
