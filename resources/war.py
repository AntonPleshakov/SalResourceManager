from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

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

ActivityRule = Callable[[UserData], Decimal]

# Each row is a forge level (1–35); columns are weapon levels
# Primitive, Medieval, Early-Modern, Modern, Space, Interstellar, Multiverse,
# Quantum, Underworld, Divine. Values are percentages from the game table.
FORGE_WEAPON_CHANCES: List[List[Decimal]] = [
    [Decimal("100.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("99.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("98.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("96.00"), Decimal("4.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("91.50"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("82.00"), Decimal("16.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("64.00"), Decimal("32.00"), Decimal("4.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("27.80"), Decimal("64.00"), Decimal("8.00"), Decimal("0.20"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("13.00"), Decimal("70.00"), Decimal("16.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("6.00"), Decimal("60.00"), Decimal("32.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("31.90"), Decimal("64.00"), Decimal("4.00"), Decimal("0.10"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("27.50"), Decimal("64.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("8.00"), Decimal("75.00"), Decimal("16.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("66.00"), Decimal("32.00"), Decimal("2.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("31.70"), Decimal("64.00"), Decimal("4.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("21.50"), Decimal("70.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("82.90"), Decimal("16.00"), Decimal("1.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("65.70"), Decimal("32.00"), Decimal("2.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("31.50"), Decimal("64.00"), Decimal("4.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("91.00"), Decimal("8.00"), Decimal("1.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("81.70"), Decimal("16.00"), Decimal("2.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("63.50"), Decimal("32.00"), Decimal("4.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("27.00"), Decimal("64.00"), Decimal("8.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("82.00"), Decimal("16.00"), Decimal("2.00"), Decimal("0.02"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("64.00"), Decimal("32.00"), Decimal("4.00"), Decimal("0.05"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("43.80"), Decimal("50.00"), Decimal("6.00"), Decimal("0.25"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("31.50"), Decimal("60.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("21.00"), Decimal("65.00"), Decimal("13.00"), Decimal("1.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("6.99"), Decimal("68.00"), Decimal("23.00"), Decimal("2.00"), Decimal("0.02")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("60.00"), Decimal("36.00"), Decimal("4.00"), Decimal("0.05")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("50.80"), Decimal("43.00"), Decimal("6.00"), Decimal("0.25")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("41.50"), Decimal("50.00"), Decimal("8.00"), Decimal("0.50")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("28.00"), Decimal("58.00"), Decimal("13.00"), Decimal("1.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("11.00"), Decimal("64.00"), Decimal("23.00"), Decimal("2.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("60.00"), Decimal("36.00"), Decimal("4.00")],
]


def forge_weapon_chances(forge_level: int) -> Sequence[Decimal]:
    if not 1 <= forge_level <= len(FORGE_WEAPON_CHANCES):
        raise ValueError(f"Unknown forge level: {forge_level}")
    return FORGE_WEAPON_CHANCES[forge_level - 1]


def weapon_points(weapon_index: int) -> int:
    if not 0 <= weapon_index < 10:
        raise ValueError(f"Unknown weapon index: {weapon_index}")
    if weapon_index <= 2:
        return 2
    if weapon_index <= 5:
        return 4
    return 5


@dataclass(frozen=True)
class WarPointsReport:
    points_by_day: Mapping[int, Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.points_by_day.values(), Decimal("0"))


class WarPointsCalculator:
    def __init__(self):
        self._rules: Mapping[WarActivity, ActivityRule] = {
            WarActivity.FORGING: self._forging_points,
        }

    @staticmethod
    def _forging_points(user: UserData) -> Decimal:
        chances = forge_weapon_chances(user.forge_level.value)
        expected_points = sum(
            Decimal(str(chance)) * weapon_points(weapon_index) / Decimal("100")
            for weapon_index, chance in enumerate(chances)
        )
        return Decimal(user.hammers.value) * expected_points

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
