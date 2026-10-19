from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path

from resources.user_data import UserData
from resources.war_rules.mount_packages import summon_packages


LEVEL_DATA = json.loads(
    Path(__file__).with_name("ascension_levels.json").read_text(encoding="utf-8")
)["systems"]
RARITIES = ("Common", "Rare", "Epic", "Legendary", "Ultimate", "Mythic")
TARGETS = {"skills": (24, "Legendary"), "pets": (37, "Legendary"),
           "mount": (31, "Epic")}


@dataclass(frozen=True)
class AscensionForecast:
    system: str
    level: int
    progress: Decimal
    required: int
    probabilities: tuple[Decimal, ...]
    target_level: int
    target_rarity: str

    @property
    def favorable(self) -> bool:
        return self.level >= self.target_level


def forecast_level(system: str, summons: Decimal) -> AscensionForecast:
    if summons < 0:
        raise ValueError("Количество призывов не может быть отрицательным")
    remaining = summons
    for level, required, *probabilities in LEVEL_DATA[system]:
        if required == 0 or remaining < required:
            target_level, target_rarity = TARGETS[system]
            return AscensionForecast(
                system, level, remaining, required,
                tuple(Decimal(str(value)) for value in probabilities),
                target_level, target_rarity,
            )
        remaining -= required
    raise ValueError("В таблице отсутствует максимальный уровень")


def resource_inputs(user: UserData, system: str) -> tuple[int, int, int]:
    return {
        "skills": (user.skills.value, user.skill_summon_cost.value, 0),
        "pets": (user.shells.value, 0, user.extra_egg_chance.value),
        "mount": (user.mount_keys.value, user.mount_summon_cost.value,
                  user.extra_mount_chance.value),
    }[system]


def available_summons(system: str, amount: int, discount: int, extra: int) -> Decimal:
    if system == "skills":
        cost = Decimal(40) * (100 - discount) / 100
        return Decimal(amount) // cost
    if system == "pets":
        base = amount // 100
    else:
        base, _, _ = summon_packages(amount, discount)
    return Decimal(base) * (1 + Decimal(extra) / 100)


def summons_to_level(system: str, level: int) -> int:
    return sum(row[1] for row in LEVEL_DATA[system] if row[0] < level)


def target_resource_cost(user: UserData, system: str) -> int:
    _, discount, extra = resource_inputs(user, system)
    required = summons_to_level(system, TARGETS[system][0])
    low, high = 0, required * 100
    while low < high:
        middle = (low + high) // 2
        if available_summons(system, middle, discount, extra) >= required:
            high = middle
        else:
            low = middle + 1
    return low


def forecast_ascension(user: UserData) -> tuple[AscensionForecast, ...]:
    return tuple(
        forecast_level(system, available_summons(system, *resource_inputs(user, system)))
        for system in ("skills", "pets", "mount")
    )
