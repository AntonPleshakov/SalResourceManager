from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import Callable, Dict, Iterable, Mapping, Sequence, Tuple

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails
from resources.war_rules.dungeons import (
    calculate_dungeon_points,
    explain_dungeon_points,
)
from resources.war_rules.forge import calculate_forge_points, explain_forge_points
from resources.war_rules.forging import (
    calculate_forging_points,
    explain_forging_points,
)
from resources.war_rules.mounts import calculate_mount_points, explain_mount_points
from resources.war_rules.pets import calculate_pet_points, explain_pet_points
from resources.war_rules.skills import calculate_skill_points, explain_skill_points
from resources.war_rules.technologies import (
    calculate_technology_points,
    explain_technology_points,
)


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

    @classmethod
    def from_storage(cls, value: str) -> "WarActivity":
        for activity in cls:
            if value in {activity.value, activity.title}:
                return activity
        raise ValueError(f"Unknown war activity: {value}")


WarStage = Tuple[WarActivity, WarActivity, WarActivity]

DEFAULT_WAR_STAGES: Dict[int, WarStage] = {
    1: (WarActivity.FORGING, WarActivity.DUNGEONS, WarActivity.SKILLS),
    2: (WarActivity.FORGE, WarActivity.TECHNOLOGIES, WarActivity.MOUNTS),
    3: (WarActivity.FORGING, WarActivity.SKILLS, WarActivity.PETS),
    4: (WarActivity.FORGE, WarActivity.DUNGEONS, WarActivity.MOUNTS),
    5: (WarActivity.FORGING, WarActivity.PETS, WarActivity.TECHNOLOGIES),
}

ActivityRule = Callable[[UserData], Decimal]
ActivityDetailsRule = Callable[[UserData], ActivityDetails]


@dataclass(frozen=True)
class WarPointsReport:
    points_by_day: Mapping[int, Decimal]
    points_by_activity_by_day: Mapping[
        int, Mapping[WarActivity, Decimal]
    ]

    @property
    def total(self) -> Decimal:
        return sum(self.points_by_day.values(), Decimal("0"))


class WarPointsCalculator:
    def __init__(self):
        self._rules: Mapping[WarActivity, ActivityRule] = {
            WarActivity.FORGING: calculate_forging_points,
            WarActivity.DUNGEONS: calculate_dungeon_points,
            WarActivity.SKILLS: calculate_skill_points,
            WarActivity.FORGE: calculate_forge_points,
            WarActivity.TECHNOLOGIES: calculate_technology_points,
            WarActivity.MOUNTS: calculate_mount_points,
            WarActivity.PETS: calculate_pet_points,
        }
        self._details_rules: Mapping[WarActivity, ActivityDetailsRule] = {
            WarActivity.FORGING: explain_forging_points,
            WarActivity.DUNGEONS: explain_dungeon_points,
            WarActivity.SKILLS: explain_skill_points,
            WarActivity.FORGE: explain_forge_points,
            WarActivity.TECHNOLOGIES: explain_technology_points,
            WarActivity.MOUNTS: explain_mount_points,
            WarActivity.PETS: explain_pet_points,
        }

    def calculate_details(
        self,
        user: UserData,
        activities: Sequence[WarActivity],
    ) -> Mapping[WarActivity, ActivityDetails]:
        return {
            activity: self._details_rules[activity](user)
            for activity in dict.fromkeys(activities)
            if activity in self._details_rules
        }

    def calculate(
        self,
        users: Iterable[UserData],
        stages: Mapping[int, WarStage],
    ) -> WarPointsReport:
        users = list(users)
        points_by_day: Dict[int, Decimal] = {}
        points_by_activity_by_day: Dict[
            int, Dict[WarActivity, Decimal]
        ] = {}
        for day, activities in sorted(stages.items()):
            activity_points: Dict[WarActivity, Decimal] = {}
            for activity in activities:
                rule = self._rules.get(activity)
                if rule is None:
                    continue
                points = sum((rule(user) for user in users), Decimal("0"))
                activity_points[activity] = (
                    activity_points.get(activity, Decimal("0")) + points
                )
            points_by_activity_by_day[day] = activity_points
            points_by_day[day] = sum(activity_points.values(), Decimal("0"))
        return WarPointsReport(points_by_day, points_by_activity_by_day)
