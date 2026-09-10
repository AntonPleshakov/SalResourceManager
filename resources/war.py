from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails
from resources.war_rules.dungeons import explain_dungeon_points
from resources.war_rules.forge import (
    explain_forge_occurrences,
    explain_forge_points,
)
from resources.war_rules.forging import explain_forging_points
from resources.war_rules.mounts import explain_mount_points
from resources.war_rules.pets import explain_pet_points
from resources.war_rules.skills import explain_skill_points
from resources.war_rules.technologies import explain_technology_points


class WarActivity(str, Enum):
    FORGING = "forging"
    DUNGEONS = "dungeons"
    SKILLS = "skills"
    FORGE = "forge"
    TECHNOLOGIES = "technologies"
    MOUNTS = "mounts"
    PETS = "pets"

    @property
    def title(self) -> str:
        return {
            WarActivity.FORGING: "Ковка",
            WarActivity.DUNGEONS: "Подземелья",
            WarActivity.SKILLS: "Навыки",
            WarActivity.FORGE: "Кузница",
            WarActivity.TECHNOLOGIES: "Технологии",
            WarActivity.MOUNTS: "Маунты",
            WarActivity.PETS: "Питомцы",
        }[self]

WarStage = Tuple[WarActivity, WarActivity, WarActivity]

WAR_STAGES: Mapping[int, WarStage] = MappingProxyType(
    {
        1: (WarActivity.FORGING, WarActivity.DUNGEONS, WarActivity.SKILLS),
        2: (WarActivity.FORGE, WarActivity.TECHNOLOGIES, WarActivity.MOUNTS),
        3: (WarActivity.FORGING, WarActivity.SKILLS, WarActivity.PETS),
        4: (WarActivity.FORGE, WarActivity.DUNGEONS, WarActivity.MOUNTS),
        5: (WarActivity.FORGING, WarActivity.PETS, WarActivity.TECHNOLOGIES),
    }
)


@dataclass(frozen=True)
class WarPointsReport:
    points_by_day: Mapping[int, Decimal]
    points_by_activity_by_day: Mapping[
        int, Mapping[WarActivity, Decimal]
    ]
    points_by_activity: Mapping[WarActivity, Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.points_by_activity.values(), Decimal("0"))


class WarPointsCalculator:
    def __init__(
        self, clan_technologies: ClanTechnologies | None = None
    ):
        self._clan_technologies = clan_technologies or ClanTechnologies()
        self._details_rules = {
            WarActivity.FORGING: explain_forging_points,
            WarActivity.DUNGEONS: explain_dungeon_points,
            WarActivity.SKILLS: explain_skill_points,
            WarActivity.FORGE: explain_forge_points,
            WarActivity.TECHNOLOGIES: explain_technology_points,
            WarActivity.MOUNTS: explain_mount_points,
            WarActivity.PETS: explain_pet_points,
        }

    def _explain(
        self, user: UserData, activity: WarActivity
    ) -> ActivityDetails:
        return self._details_rules[activity](user, self._clan_technologies)

    def _apply_day_bonus(self, points: Decimal, day: int | None) -> Decimal:
        if day is None:
            return points
        return points * self._clan_technologies.day_multiplier(day)

    def calculate_details(
        self,
        user: UserData,
        activities: Sequence[WarActivity],
    ) -> Mapping[WarActivity, ActivityDetails]:
        return {
            activity: self._explain(user, activity)
            for activity in dict.fromkeys(activities)
            if activity in self._details_rules
        }

    def calculate_occurrence_points(
        self,
        user: UserData,
        activity: WarActivity,
        occurrence_count: int,
        days: Sequence[int] = (),
    ) -> Tuple[Decimal, ...]:
        if occurrence_count <= 0:
            return ()
        if activity == WarActivity.FORGE:
            points = tuple(
                details.points
                for details in explain_forge_occurrences(
                    user,
                    occurrence_count,
                    self._clan_technologies,
                )
            )
        else:
            details = self._explain(user, activity)
            points = (
                details.points,
                *((details.repeatable_points,) * (occurrence_count - 1)),
            )
        return tuple(
            self._apply_day_bonus(
                occurrence_points,
                days[index] if index < len(days) else None,
            )
            for index, occurrence_points in enumerate(points)
        )

    def calculate(
        self,
        users: Iterable[UserData],
        stages: Mapping[int, WarStage],
    ) -> WarPointsReport:
        users = list(users)
        occurrence_counts = Counter(
            activity
            for activities in stages.values()
            for activity in activities
        )
        occurrence_days = {
            activity: tuple(
                day
                for day, activities in sorted(stages.items())
                for candidate in activities
                if candidate == activity
            )
            for activity in occurrence_counts
        }
        user_schedules = [
            {
                activity: self.calculate_occurrence_points(
                    user,
                    activity,
                    occurrence_counts[activity],
                    occurrence_days[activity],
                )
                for activity in occurrence_counts
                if activity in self._details_rules
            }
            for user in users
        ]
        points_by_activity = {
            activity: sum(
                (
                    sum(schedule[activity], Decimal("0"))
                    for schedule in user_schedules
                ),
                Decimal("0"),
            )
            for activity in occurrence_counts
            if activity in self._details_rules
        }
        occurrence_indexes: Counter[WarActivity] = Counter()
        points_by_day: Dict[int, Decimal] = {}
        points_by_activity_by_day: Dict[
            int, Dict[WarActivity, Decimal]
        ] = {}
        for day, activities in sorted(stages.items()):
            activity_points: Dict[WarActivity, Decimal] = {}
            for activity in activities:
                if activity not in self._details_rules:
                    continue
                occurrence_index = occurrence_indexes[activity]
                if activity == WarActivity.FORGE:
                    points = sum(
                        (
                            schedule[activity][occurrence_index]
                            for schedule in user_schedules
                        ),
                        Decimal("0"),
                    )
                else:
                    points = sum(
                        (
                            self._apply_day_bonus(
                                self._explain(user, activity).points,
                                day,
                            )
                            for user in users
                        ),
                        Decimal("0"),
                    )
                occurrence_indexes[activity] += 1
                activity_points[activity] = (
                    activity_points.get(activity, Decimal("0")) + points
                )
            points_by_activity_by_day[day] = activity_points
            points_by_day[day] = sum(activity_points.values(), Decimal("0"))
        return WarPointsReport(
            points_by_day,
            points_by_activity_by_day,
            points_by_activity,
        )
