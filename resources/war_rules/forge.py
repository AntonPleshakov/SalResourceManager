from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


FORGE_POINTS_PER_THOUSAND_COINS = 38
FORGE_RESET_UPGRADES = 8
FORGE_MAX_LEVEL_FOR_SECOND_EVENT = 22
FORGE_TOTAL_COSTS: Tuple[int, ...] = (
    0,
    400,
    700,
    1_500,
    3_500,
    10_000,
    25_000,
    50_000,
    100_000,
    150_000,
    250_000,
    350_000,
    450_000,
    600_000,
    800_000,
    910_000,
    1_020_000,
    1_130_000,
    1_240_000,
    1_350_000,
    1_460_000,
    1_570_000,
    1_680_000,
    1_790_000,
    1_900_000,
    2_010_000,
    2_120_000,
    2_230_000,
    2_340_000,
    2_450_000,
    2_560_000,
    2_670_000,
    2_780_000,
    2_890_000,
    3_000_000,
)


def _forge_total_cost(forge_level: int) -> int:
    if forge_level == len(FORGE_TOTAL_COSTS):
        return sum(FORGE_TOTAL_COSTS[1 : FORGE_RESET_UPGRADES + 1])
    return FORGE_TOTAL_COSTS[forge_level]


def explain_forge_level(forge_level: int) -> ActivityDetails:
    total_cost = _forge_total_cost(forge_level)
    counted_thousands = total_cost // 1_000
    points = Decimal(counted_thousands * FORGE_POINTS_PER_THOUSAND_COINS)
    calculations = []
    if forge_level == len(FORGE_TOTAL_COSTS):
        calculations.append(
            f"После сброса кузницы учитывается стоимость уровней 1–"
            f"{FORGE_RESET_UPGRADES}"
        )
    calculations.extend(
        [
            f"Стоимость улучшений: {format_calculation_number(total_cost)} монет",
            f"Засчитываемые тысячи монет: {counted_thousands}",
            f"{counted_thousands} × {FORGE_POINTS_PER_THOUSAND_COINS} = "
            f"{format_calculation_number(points)} очков",
        ]
    )
    return ActivityDetails(
        consumable_points=points,
        repeatable_points=Decimal("0"),
        inputs=(f"Уровень кузницы: {forge_level}",),
        calculations=tuple(calculations),
    )


def explain_forge_points(user: UserData) -> ActivityDetails:
    return explain_forge_level(user.forge_level.value)


def calculate_forge_points(user: UserData) -> Decimal:
    return explain_forge_points(user).points


def explain_forge_occurrences(
    user: UserData, occurrence_count: int
) -> Tuple[ActivityDetails, ...]:
    if occurrence_count <= 0:
        return ()

    forge_level = user.forge_level.value
    occurrences = [explain_forge_level(forge_level)]
    if occurrence_count >= 2:
        if forge_level <= FORGE_MAX_LEVEL_FOR_SECOND_EVENT:
            occurrences.append(explain_forge_level(forge_level + 1))
        else:
            occurrences.append(
                ActivityDetails(
                    consumable_points=Decimal("0"),
                    repeatable_points=Decimal("0"),
                    inputs=(f"Уровень кузницы: {forge_level}",),
                    calculations=(
                        f"Улучшение до уровня {forge_level + 1} не завершится "
                        "между вторым и четвёртым днями войны",
                    ),
                )
            )
    while len(occurrences) < occurrence_count:
        occurrences.append(
            ActivityDetails(
                consumable_points=Decimal("0"),
                repeatable_points=Decimal("0"),
                inputs=(f"Уровень кузницы: {forge_level}",),
                calculations=(
                    "Для дополнительных дней кузницы нет настроенного "
                    "временного интервала",
                ),
            )
        )
    return tuple(occurrences)
