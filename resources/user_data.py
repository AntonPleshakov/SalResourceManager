from dataclasses import dataclass
import re
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
    ResourceField("skills", "Билетики навыков"),
    ResourceField("shells", "Скорлупа"),
    ResourceField("hammers", "Молотки"),
    ResourceField("gems", "Гемы"),
    ResourceField("pets", "Питомцы"),
    ResourceField("unmerged_mounts", "Необъединённые маунты"),
)

TECHNOLOGY_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("forge_level", "Уровень кузницы"),
    ResourceField("skill_summon_cost", "Снижение стоимости призыва навыков (%)"),
    ResourceField("extra_egg_chance", "Доп. шанс на яйцо"),
    ResourceField("mount_summon_cost", "Снижение стоимости призыва маунта (%)"),
    ResourceField("extra_mount_chance", "Шанс на доп. маунта"),
)

EDITABLE_FIELDS: Dict[str, ResourceField] = {
    field.name: field for field in RESOURCE_FIELDS + TECHNOLOGY_FIELDS
}
THOUSAND_INPUT_FIELDS = frozenset(
    {"mount_keys", "skills", "shells", "hammers"}
)


def parse_non_negative_int(value: str) -> int:
    normalized = value.strip().replace(" ", "").replace("_", "")
    if not normalized.isdigit():
        raise ValueError("Value must be a non-negative integer")
    return int(normalized)


def parse_editable_field_value(field_name: str, value: str) -> int:
    if field_name not in THOUSAND_INPUT_FIELDS:
        return parse_non_negative_int(value)

    normalized = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d)?", normalized):
        raise ValueError("Value must be a non-negative number with one decimal place")
    whole, _, fraction = normalized.partition(".")
    return int(whole) * 1_000 + int(fraction or "0") * 100


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
        forge_level: int = 1,
        skill_summon_cost: int = 0,
        extra_egg_chance: int = 0,
        mount_summon_cost: int = 0,
        extra_mount_chance: int = 0,
    ):
        self.user_id = IntParam("Telegram ID", user_id)
        self.username = StrParam("Пользователь", username)
        self.mount_keys = IntParam("Ключи маунтов", mount_keys)
        self.skills = IntParam("Билетики навыков", skills)
        self.shells = IntParam("Скорлупа", shells)
        self.hammers = IntParam("Молотки", hammers)
        self.gems = IntParam("Гемы", gems)
        self.pets = IntParam("Питомцы", pets)
        self.unmerged_mounts = IntParam(
            "Необъединённые маунты", unmerged_mounts
        )
        self.forge_level = IntParam("Уровень кузницы", forge_level)
        self.skill_summon_cost = IntParam(
            "Снижение стоимости призыва навыков (%)", skill_summon_cost
        )
        self.extra_egg_chance = IntParam(
            "Доп. шанс на яйцо", extra_egg_chance
        )
        self.mount_summon_cost = IntParam(
            "Снижение стоимости призыва маунта (%)", mount_summon_cost
        )
        self.extra_mount_chance = IntParam(
            "Шанс на доп. маунта", extra_mount_chance
        )
