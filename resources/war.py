from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, Mapping, Tuple

from resources.user_data import UserData


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

ActivityRule = Callable[[UserData], int]


@dataclass(frozen=True)
class WarPointsReport:
    points_by_day: Mapping[int, int]

    @property
    def total(self) -> int:
        return sum(self.points_by_day.values())


class WarPointsCalculator:
    """Extensible calculator; scoring rules are added when their formulas are known."""

    def __init__(self, rules: Mapping[WarActivity, ActivityRule] = None):
        self._rules = dict(rules or {})

    def calculate(
        self,
        users: Iterable[UserData],
        stages: Mapping[int, WarStage],
    ) -> WarPointsReport:
        users = list(users)
        points_by_day = {
            day: sum(
                rule(user)
                for activity in activities
                if (rule := self._rules.get(activity)) is not None
                for user in users
            )
            for day, activities in sorted(stages.items())
        }
        return WarPointsReport(points_by_day)
