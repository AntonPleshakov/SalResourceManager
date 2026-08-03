from decimal import Decimal

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number

FIFTH_TIER_TECHNOLOGY_POINTS = 163_260
FOURTH_TIER_TECHNOLOGY_POINTS = 86_040


def explain_technology_points(_: UserData) -> ActivityDetails:
    points = Decimal(
        FIFTH_TIER_TECHNOLOGY_POINTS + FOURTH_TIER_TECHNOLOGY_POINTS
    )
    return ActivityDetails(
        points=points,
        inputs=("Фиксированный расчёт без расхода ресурсов пользователя",),
        calculations=(
            f"Технология V уровня: "
            f"{format_calculation_number(FIFTH_TIER_TECHNOLOGY_POINTS)} очков",
            f"Технология IV уровня: "
            f"{format_calculation_number(FOURTH_TIER_TECHNOLOGY_POINTS)} очков",
            f"{format_calculation_number(FIFTH_TIER_TECHNOLOGY_POINTS)} + "
            f"{format_calculation_number(FOURTH_TIER_TECHNOLOGY_POINTS)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def calculate_technology_points(user: UserData) -> Decimal:
    return explain_technology_points(user).points
