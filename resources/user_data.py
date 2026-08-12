from dataclasses import dataclass
from datetime import date
import re
from typing import Dict, Optional, Tuple

from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam


@dataclass(frozen=True)
class ResourceField:
    name: str
    title: str


@dataclass(frozen=True)
class GameAccount:
    account_id: int
    user_id: int
    username: str
    tag: str
    is_active: bool = False


RESOURCE_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("mount_keys", "Ключи маунтов"),
    ResourceField("skills", "Билетики навыков"),
    ResourceField("shells", "Скорлупа"),
    ResourceField("hammers", "Молотки"),
    ResourceField("pets", "Питомцы и яйца"),
    ResourceField("unmerged_mounts", "Необъединённые маунты"),
)

TECHNOLOGY_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("forge_level", "Уровень кузницы"),
    ResourceField("skill_summon_cost", "Снижение стоимости призыва навыков (%)"),
    ResourceField("extra_egg_chance", "Доп. шанс на яйцо"),
    ResourceField("mount_summon_cost", "Снижение стоимости призыва маунта (%)"),
    ResourceField("extra_mount_chance", "Шанс на доп. маунта"),
)
PET_SETTINGS_FIELDS: Tuple[ResourceField, ...] = (
    ResourceField("eggs_per_hatch_batch", "Яиц в одном пакете"),
    ResourceField("max_egg_level", "Максимальный уровень яйца"),
    ResourceField("hatch_batches_common", "Пакеты Common в день"),
    ResourceField("hatch_batches_rare", "Пакеты Rare в день"),
    ResourceField("hatch_batches_epic", "Пакеты Epic в день"),
    ResourceField("hatch_batches_legendary", "Пакеты Legendary в день"),
    ResourceField("hatch_batches_ultimate", "Пакеты Ultimate в день"),
    ResourceField("hatch_batches_mythic", "Пакеты Mythic в день"),
)
TRACKED_FIELDS: Tuple[ResourceField, ...] = RESOURCE_FIELDS + TECHNOLOGY_FIELDS
UPDATED_AT_FIELDS: Dict[str, str] = {
    field.name: f"{field.name}_updated_on" for field in TRACKED_FIELDS
}

EDITABLE_FIELDS: Dict[str, ResourceField] = {
    field.name: field for field in TRACKED_FIELDS + PET_SETTINGS_FIELDS
}
THOUSAND_INPUT_FIELDS = frozenset(
    {"mount_keys", "skills", "shells", "hammers"}
)


def validate_editable_field_value(field_name: str, value: int) -> int:
    if field_name not in EDITABLE_FIELDS:
        raise ValueError(f"Показатель не найден: {field_name}")
    if not isinstance(value, int) or value < 0:
        raise ValueError("Нужно ввести целое неотрицательное число")
    if field_name == "forge_level" and not 1 <= value <= 35:
        raise ValueError("Уровень кузницы должен быть от 1 до 35")
    if field_name == "skill_summon_cost" and not 0 <= value <= 25:
        raise ValueError(
            "Снижение стоимости призыва навыков должно быть от 0 до 25%"
        )
    if field_name == "mount_summon_cost" and not 0 <= value <= 25:
        raise ValueError(
            "Снижение стоимости призыва маунта должно быть от 0 до 25%"
        )
    if field_name == "extra_mount_chance" and not 0 <= value <= 50:
        raise ValueError(
            "Шанс на дополнительного маунта должен быть от 0 до 50%"
        )
    if field_name == "eggs_per_hatch_batch" and not 2 <= value <= 4:
        raise ValueError("Количество яиц в одном пакете должно быть от 2 до 4")
    if field_name == "max_egg_level" and not 1 <= value <= 6:
        raise ValueError("Уровень яйца должен быть от 1 до 6")
    return value


def parse_non_negative_int(value: str) -> int:
    normalized = value.strip().replace(" ", "").replace("_", "")
    if not normalized.isdigit():
        raise ValueError("Нужно ввести целое неотрицательное число")
    return int(normalized)


def parse_editable_field_value(field_name: str, value: str) -> int:
    if field_name not in THOUSAND_INPUT_FIELDS:
        parsed = parse_non_negative_int(value)
        return validate_editable_field_value(field_name, parsed)

    normalized = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d{1,3})?", normalized):
        raise ValueError(
            "Нужно ввести неотрицательное число не более чем с тремя "
            "знаками после запятой или точки"
        )
    whole, _, fraction = normalized.partition(".")
    parsed = int(whole) * 1_000 + int((fraction or "0").ljust(3, "0"))
    return validate_editable_field_value(field_name, parsed)


class UserData(Parameters):
    def __init__(
        self,
        account_id: int = 0,
        user_id: int = 0,
        username: str = "",
        tag: str = "",
        mount_keys: int = 0,
        skills: int = 0,
        shells: int = 0,
        hammers: int = 0,
        pets: int = 0,
        unmerged_mounts: int = 0,
        forge_level: int = 1,
        skill_summon_cost: int = 0,
        extra_egg_chance: int = 0,
        mount_summon_cost: int = 0,
        extra_mount_chance: int = 0,
        eggs_per_hatch_batch: int = 4,
        max_egg_level: int = 6,
        hatch_batches_common: int = 0,
        hatch_batches_rare: int = 0,
        hatch_batches_epic: int = 0,
        hatch_batches_legendary: int = 0,
        hatch_batches_ultimate: int = 1,
        hatch_batches_mythic: int = 1,
        mount_keys_updated_on: str = "",
        skills_updated_on: str = "",
        shells_updated_on: str = "",
        hammers_updated_on: str = "",
        pets_updated_on: str = "",
        unmerged_mounts_updated_on: str = "",
        forge_level_updated_on: str = "",
        skill_summon_cost_updated_on: str = "",
        extra_egg_chance_updated_on: str = "",
        mount_summon_cost_updated_on: str = "",
        extra_mount_chance_updated_on: str = "",
    ):
        self.account_id = IntParam("Игровой аккаунт ID", account_id)
        self.user_id = IntParam("Telegram ID", user_id)
        self.username = StrParam("Telegram username", username)
        self.tag = StrParam("Имя игрового аккаунта", tag)
        self.mount_keys = IntParam("Ключи маунтов", mount_keys)
        self.mount_keys_updated_on = StrParam(
            "Ключи маунтов — обновлено", mount_keys_updated_on
        )
        self.skills = IntParam("Билетики навыков", skills)
        self.skills_updated_on = StrParam(
            "Билетики навыков — обновлено", skills_updated_on
        )
        self.shells = IntParam("Скорлупа", shells)
        self.shells_updated_on = StrParam(
            "Скорлупа — обновлено", shells_updated_on
        )
        self.hammers = IntParam("Молотки", hammers)
        self.hammers_updated_on = StrParam(
            "Молотки — обновлено", hammers_updated_on
        )
        self.pets = IntParam("Питомцы и яйца", pets)
        self.pets_updated_on = StrParam(
            "Питомцы и яйца — обновлено", pets_updated_on
        )
        self.unmerged_mounts = IntParam(
            "Необъединённые маунты", unmerged_mounts
        )
        self.unmerged_mounts_updated_on = StrParam(
            "Необъединённые маунты — обновлено", unmerged_mounts_updated_on
        )
        self.forge_level = IntParam("Уровень кузницы", forge_level)
        self.forge_level_updated_on = StrParam(
            "Уровень кузницы — обновлено", forge_level_updated_on
        )
        self.skill_summon_cost = IntParam(
            "Снижение стоимости призыва навыков (%)", skill_summon_cost
        )
        self.skill_summon_cost_updated_on = StrParam(
            "Снижение стоимости призыва навыков (%) — обновлено",
            skill_summon_cost_updated_on,
        )
        self.extra_egg_chance = IntParam(
            "Доп. шанс на яйцо", extra_egg_chance
        )
        self.extra_egg_chance_updated_on = StrParam(
            "Доп. шанс на яйцо — обновлено", extra_egg_chance_updated_on
        )
        self.mount_summon_cost = IntParam(
            "Снижение стоимости призыва маунта (%)", mount_summon_cost
        )
        self.mount_summon_cost_updated_on = StrParam(
            "Снижение стоимости призыва маунта (%) — обновлено",
            mount_summon_cost_updated_on,
        )
        self.extra_mount_chance = IntParam(
            "Шанс на доп. маунта", extra_mount_chance
        )
        self.extra_mount_chance_updated_on = StrParam(
            "Шанс на доп. маунта — обновлено", extra_mount_chance_updated_on
        )
        self.eggs_per_hatch_batch = IntParam(
            "Яиц в одном пакете", eggs_per_hatch_batch
        )
        self.max_egg_level = IntParam(
            "Максимальный уровень яйца", max_egg_level
        )
        self.hatch_batches_common = IntParam(
            "Пакеты Common в день", hatch_batches_common
        )
        self.hatch_batches_rare = IntParam(
            "Пакеты Rare в день", hatch_batches_rare
        )
        self.hatch_batches_epic = IntParam(
            "Пакеты Epic в день", hatch_batches_epic
        )
        self.hatch_batches_legendary = IntParam(
            "Пакеты Legendary в день", hatch_batches_legendary
        )
        self.hatch_batches_ultimate = IntParam(
            "Пакеты Ultimate в день", hatch_batches_ultimate
        )
        self.hatch_batches_mythic = IntParam(
            "Пакеты Mythic в день", hatch_batches_mythic
        )

    def get_updated_on(self, field_name: str) -> Optional[date]:
        parameter_name = UPDATED_AT_FIELDS.get(field_name)
        if parameter_name is None:
            raise ValueError(f"Показатель не найден: {field_name}")
        value = getattr(self, parameter_name).value
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def mark_updated(self, field_name: str, updated_on: date) -> None:
        parameter_name = UPDATED_AT_FIELDS.get(field_name)
        if parameter_name is None:
            raise ValueError(f"Показатель не найден: {field_name}")
        getattr(self, parameter_name).value = updated_on.isoformat()
