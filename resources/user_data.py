from dataclasses import dataclass
from typing import Dict, Tuple

from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam


@dataclass(frozen=True)
class ResourceField:
    name: str
    title: str


RESOURCE_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("mount_keys", "Ключи маунтов"),
    ResourceField("skills", "Навыки"),
    ResourceField("shells", "Скорлупа"),
    ResourceField("hammers", "Молотки"),
    ResourceField("gems", "Гемы"),
    ResourceField("pets", "Питомцы"),
    ResourceField("unmerged_mounts", "Необъединённые маунты"),
)

TECHNOLOGY_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("skill_summon_cost", "Стоимость призыва навыков"),
    ResourceField("extra_egg_chance", "Доп. шанс на яйцо"),
    ResourceField("mount_summon_cost", "Стоимость призыва маунта"),
    ResourceField("extra_mount_chance", "Шанс на доп. маунта"),
)

EDITABLE_FIELDS: Dict[str, ResourceField] = {
    field.name: field for field in RESOURCE_FIELDS + TECHNOLOGY_FIELDS
}


def parse_non_negative_int(value: str) -> int:
    normalized = value.strip().replace(" ", "").replace("_", "")
    if not normalized.isdigit():
        raise ValueError("Value must be a non-negative integer")
    return int(normalized)


class UserData(Parameters):
    def __init__(
        self,
        user_id: int = 0,
        username: str = "",
        mount_keys: int = 0,
        skills: int = 0,
        shells: int = 0,
        hammers: int = 0,
        gems: int = 0,
        pets: int = 0,
        unmerged_mounts: int = 0,
        skill_summon_cost: int = 0,
        extra_egg_chance: int = 0,
        mount_summon_cost: int = 0,
        extra_mount_chance: int = 0,
    ):
        self.user_id = IntParam("Telegram ID", user_id)
        self.username = StrParam("Пользователь", username)
        self.mount_keys = IntParam("Ключи маунтов", mount_keys)
        self.skills = IntParam("Навыки", skills)
        self.shells = IntParam("Скорлупа", shells)
        self.hammers = IntParam("Молотки", hammers)
        self.gems = IntParam("Гемы", gems)
        self.pets = IntParam("Питомцы", pets)
        self.unmerged_mounts = IntParam(
            "Необъединённые маунты", unmerged_mounts
        )
        self.skill_summon_cost = IntParam(
            "Стоимость призыва навыков", skill_summon_cost
        )
        self.extra_egg_chance = IntParam(
            "Доп. шанс на яйцо", extra_egg_chance
        )
        self.mount_summon_cost = IntParam(
            "Стоимость призыва маунта", mount_summon_cost
        )
        self.extra_mount_chance = IntParam(
            "Шанс на доп. маунта", extra_mount_chance
        )
