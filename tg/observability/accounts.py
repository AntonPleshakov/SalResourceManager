from collections import Counter
from typing import Callable, Iterable

from prometheus_client import CollectorRegistry, REGISTRY
from prometheus_client.core import GaugeMetricFamily


def _single_value_metric(
    name: str, description: str, value: int
) -> GaugeMetricFamily:
    metric = GaugeMetricFamily(name, description)
    metric.add_metric([], value)
    return metric


class PlayerAccountCollector:
    def __init__(self, account_counts: Callable[[], Iterable[int]]) -> None:
        self._account_counts = account_counts

    def collect(self):
        account_counts = list(self._account_counts())
        yield _single_value_metric(
            "srm_users",
            "Number of Telegram users with at least one game account.",
            len(account_counts),
        )
        yield _single_value_metric(
            "srm_accounts",
            "Number of game accounts.",
            sum(account_counts),
        )
        distribution = GaugeMetricFamily(
            "srm_users_by_account_count",
            "Number of Telegram users grouped by their game account count.",
            labels=("account_count",),
        )
        for account_count, user_count in sorted(Counter(account_counts).items()):
            distribution.add_metric([str(account_count)], user_count)
        yield distribution


def register_player_account_metrics(
    account_counts: Callable[[], Iterable[int]],
    registry: CollectorRegistry = REGISTRY,
) -> PlayerAccountCollector:
    collector = PlayerAccountCollector(account_counts)
    registry.register(collector)
    return collector
