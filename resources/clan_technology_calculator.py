from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable, Mapping

from resources.clan_technologies import (
    CLAN_TECHNOLOGY_DEFINITIONS,
    ClanTechnologyDefinition,
    ClanTechnologies,
)
from resources.user_data import UserData
from resources.war import WarPointsCalculator, WarStage


@dataclass(frozen=True)
class ClanTechnologyRecommendation:
    definition: ClanTechnologyDefinition
    current_level: int
    points_gain: Decimal

    @property
    def next_level(self) -> int:
        return self.current_level + 1

    @property
    def points_per_flask(self) -> Decimal:
        return self.points_gain / Decimal(self.definition.flask_cost)

    @property
    def levels_to_max(self) -> int:
        return self.definition.max_level - self.current_level

    @property
    def flasks_to_max(self) -> int:
        return self.levels_to_max * self.definition.flask_cost

    @property
    def max_points_gain(self) -> Decimal:
        return self.points_gain * self.levels_to_max

def rank_clan_technology_upgrades(
    users: Iterable[UserData],
    technologies: ClanTechnologies,
    stages: Mapping[int, WarStage],
) -> tuple[ClanTechnologyRecommendation, ...]:
    users = tuple(users)
    baseline = WarPointsCalculator(technologies).calculate(users, stages).total
    recommendations = []
    for definition in CLAN_TECHNOLOGY_DEFINITIONS:
        if not definition.affects_war_points:
            continue
        current_level = getattr(technologies, definition.name)
        if current_level >= definition.max_level:
            continue
        upgraded = replace(
            technologies,
            **{definition.name: current_level + 1},
        )
        upgraded_total = WarPointsCalculator(upgraded).calculate(
            users, stages
        ).total
        recommendations.append(
            ClanTechnologyRecommendation(
                definition=definition,
                current_level=current_level,
                points_gain=upgraded_total - baseline,
            )
        )
    return tuple(
        sorted(
            recommendations,
            key=lambda recommendation: (
                recommendation.points_per_flask,
                recommendation.points_gain,
            ),
            reverse=True,
        )
    )
