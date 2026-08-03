from decimal import Decimal
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


PET_OR_EGG_MERGE_POINTS = 2_250
SHELLS_PER_EGG = 100
EGGS_PER_HATCH_BATCH = 4
SIXTH_LEVEL_EGG_POINTS = 46_080
FIFTH_LEVEL_EGG_POINTS = 23_040
MAX_HATCHING_POINTS_IN_ADVANCE = (
    SIXTH_LEVEL_EGG_POINTS * Decimal(EGGS_PER_HATCH_BATCH)
)
MAX_HATCHING_POINTS_PER_DAY = (
    Decimal(SIXTH_LEVEL_EGG_POINTS) * Decimal(EGGS_PER_HATCH_BATCH)
    + Decimal(FIFTH_LEVEL_EGG_POINTS) * Decimal(EGGS_PER_HATCH_BATCH)
)


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
    points = merge_points + MAX_HATCHING_POINTS_PER_DAY + MAX_HATCHING_POINTS_IN_ADVANCE
    return ActivityDetails(
        points=points,
        inputs=(
            f"Скорлупа: {format_calculation_number(user.shells.value)}",
            f"Дополнительный шанс яйца: {user.extra_egg_chance.value}%",
            f"Питомцы и яйца для объединения: "
            f"{format_calculation_number(user.pets.value)}",
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
            f"Вылупление в день войны: 4 × "
            f"{format_calculation_number(SIXTH_LEVEL_EGG_POINTS)} + 4 × "
            f"{format_calculation_number(FIFTH_LEVEL_EGG_POINTS)} = "
            f"{format_calculation_number(MAX_HATCHING_POINTS_PER_DAY)} очков",
            f"Заранее подготовленное вылупление: 4 × "
            f"{format_calculation_number(SIXTH_LEVEL_EGG_POINTS)} = "
            f"{format_calculation_number(MAX_HATCHING_POINTS_IN_ADVANCE)} очков",
            f"Итого: {format_calculation_number(merge_points)} + "
            f"{format_calculation_number(MAX_HATCHING_POINTS_PER_DAY)} + "
            f"{format_calculation_number(MAX_HATCHING_POINTS_IN_ADVANCE)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def _purchased_egg_count(user: UserData) -> Decimal:
    base_eggs = Decimal(user.shells.value) / SHELLS_PER_EGG
    return base_eggs * (
        Decimal("1") + Decimal(user.extra_egg_chance.value) / Decimal("100")
    )
