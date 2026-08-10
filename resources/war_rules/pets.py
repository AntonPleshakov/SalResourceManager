from decimal import Decimal

from resources.egg_levels import (
    EGG_LEVELS,
    EggLevel,
    format_hatch_batch_count,
)
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


PET_OR_EGG_MERGE_POINTS = 2_250
SHELLS_PER_EGG = 100
COMMON_EGG_POINTS = EggLevel.COMMON.points
RARE_EGG_POINTS = EggLevel.RARE.points
EPIC_EGG_POINTS = EggLevel.EPIC.points
LEGENDARY_EGG_POINTS = EggLevel.LEGENDARY.points
ULTIMATE_EGG_POINTS = EggLevel.ULTIMATE.points
MYTHIC_EGG_POINTS = EggLevel.MYTHIC.points


def calculate_pet_points(user: UserData) -> Decimal:
    return explain_pet_points(user).points


def explain_pet_points(user: UserData) -> ActivityDetails:
    base_eggs = Decimal(user.shells.value) / SHELLS_PER_EGG
    egg_multiplier = (
        Decimal("1")
        + Decimal(user.extra_egg_chance.value) / Decimal("100")
    )
    eggs = _purchased_egg_count(user)
    merge_points = (Decimal(user.pets.value) + eggs) * PET_OR_EGG_MERGE_POINTS

    eggs_per_batch = user.eggs_per_hatch_batch.value
    max_level = EggLevel(user.max_egg_level.value)
    daily_hatching_points = _daily_hatching_points(user)
    advance_hatching_points = Decimal(max_level.points * eggs_per_batch)
    points = merge_points + daily_hatching_points + advance_hatching_points

    daily_batch_lines = tuple(
        f"{level.label}: "
        f"{format_hatch_batch_count(getattr(user, level.batch_field_name).value)}"
        for level in reversed(EGG_LEVELS)
        if level <= max_level
        and getattr(user, level.batch_field_name).value > 0
    )
    if not daily_batch_lines:
        daily_batch_lines = ("Нет пакетов для вылупления",)

    return ActivityDetails(
        consumable_points=merge_points + advance_hatching_points,
        repeatable_points=daily_hatching_points,
        inputs=(
            f"Скорлупа: {format_calculation_number(user.shells.value)}",
            f"Дополнительный шанс яйца: {user.extra_egg_chance.value}%",
            f"Питомцы и яйца для объединения: "
            f"{format_calculation_number(user.pets.value)}",
            f"Яиц в одном пакете: {eggs_per_batch}",
            f"Максимальный уровень яйца: {max_level.label}",
            *(f"Вылупление в день — {line}" for line in daily_batch_lines),
        ),
        calculations=(
            f"Базовые яйца: {format_calculation_number(user.shells.value)} ÷ "
            f"{SHELLS_PER_EGG} = {format_calculation_number(base_eggs)}",
            f"Яйца с учётом доп. шанса: "
            f"{format_calculation_number(base_eggs)} × "
            f"{format_calculation_number(egg_multiplier)} = "
            f"{format_calculation_number(eggs)}",
            f"Объединение: ({format_calculation_number(user.pets.value)} + "
            f"{format_calculation_number(eggs)}) × "
            f"{format_calculation_number(PET_OR_EGG_MERGE_POINTS)} = "
            f"{format_calculation_number(merge_points)} очков",
            _daily_hatching_calculation(user, max_level),
            f"Заранее подготовленное вылупление: 1 пакет × "
            f"{eggs_per_batch} яйца × "
            f"{format_calculation_number(max_level.points)} = "
            f"{format_calculation_number(advance_hatching_points)} очков",
            f"Итого: {format_calculation_number(merge_points)} + "
            f"{format_calculation_number(daily_hatching_points)} + "
            f"{format_calculation_number(advance_hatching_points)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def _daily_hatching_points(user: UserData) -> Decimal:
    max_level = EggLevel(user.max_egg_level.value)
    eggs_per_batch = user.eggs_per_hatch_batch.value
    return sum(
        (
            Decimal(getattr(user, level.batch_field_name).value)
            * eggs_per_batch
            * level.points
            for level in EGG_LEVELS
            if level <= max_level
        ),
        Decimal("0"),
    )


def _daily_hatching_calculation(user: UserData, max_level: EggLevel) -> str:
    parts = []
    for level in reversed(EGG_LEVELS):
        if level > max_level:
            continue
        batches = getattr(user, level.batch_field_name).value
        if batches <= 0:
            continue
        parts.append(
            f"{format_hatch_batch_count(batches)} {level.english_name} × "
            f"{user.eggs_per_hatch_batch.value} яйца × "
            f"{format_calculation_number(level.points)}"
        )
    expression = " + ".join(parts) if parts else "нет пакетов"
    return (
        f"Вылупление в день войны: {expression} = "
        f"{format_calculation_number(_daily_hatching_points(user))} очков"
    )


def _purchased_egg_count(user: UserData) -> Decimal:
    base_eggs = Decimal(user.shells.value) / SHELLS_PER_EGG
    return base_eggs * (
        Decimal("1") + Decimal(user.extra_egg_chance.value) / Decimal("100")
    )
