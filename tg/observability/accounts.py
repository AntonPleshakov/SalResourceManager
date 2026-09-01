from collections import Counter
from typing import Callable, Iterable

from prometheus_client import CollectorRegistry, REGISTRY
from prometheus_client.core import GaugeMetricFamily


ClanAccountCounts = tuple[int, str, int, int]


def _single_value_metric(
    name: str, description: str, value: int
) -> GaugeMetricFamily:
    metric = GaugeMetricFamily(name, description)
    metric.add_metric([], value)
    return metric


def _empty_clan_account_counts() -> Iterable[ClanAccountCounts]:
    return ()


class PlayerAccountCollector:
    def __init__(
        self,
        account_counts: Callable[[], Iterable[int]],
        clan_account_counts: Callable[
            [], Iterable[ClanAccountCounts]
        ] = _empty_clan_account_counts,
    ) -> None:
        self._account_counts = account_counts
        self._clan_account_counts = clan_account_counts

    def collect(self):
        account_counts = list(self._account_counts())
        clan_account_counts = list(self._clan_account_counts())
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

        yield _single_value_metric(
            "srm_clans",
            "Number of registered clans.",
            len(clan_account_counts),
        )
        clan_users = GaugeMetricFamily(
            "srm_clan_users",
            "Number of Telegram users with game accounts in each clan.",
            labels=("clan_id", "clan_title"),
        )
        clan_accounts = GaugeMetricFamily(
            "srm_clan_accounts",
            "Number of game accounts in each clan.",
            labels=("clan_id", "clan_title"),
        )
        for clan_id, clan_title, user_count, account_count in clan_account_counts:
            labels = [str(clan_id), clan_title]
            clan_users.add_metric(labels, user_count)
            clan_accounts.add_metric(labels, account_count)
        yield clan_users
        yield clan_accounts


def register_player_account_metrics(
    account_counts: Callable[[], Iterable[int]],
    registry: CollectorRegistry = REGISTRY,
    *,
    clan_account_counts: Callable[
        [], Iterable[ClanAccountCounts]
    ] = _empty_clan_account_counts,
) -> PlayerAccountCollector:
    collector = PlayerAccountCollector(account_counts, clan_account_counts)
    registry.register(collector)
    return collector
