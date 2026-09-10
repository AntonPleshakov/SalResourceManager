from decimal import Decimal

from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number

FIFTH_TIER_TECHNOLOGY_POINTS = 163_260
FOURTH_TIER_TECHNOLOGY_POINTS = 86_040


def explain_technology_points(
    _: UserData,
    clan_technologies: ClanTechnologies = ClanTechnologies(),
) -> ActivityDetails:
    base_points = Decimal(
        FIFTH_TIER_TECHNOLOGY_POINTS + FOURTH_TIER_TECHNOLOGY_POINTS
    )
    multiplier = clan_technologies.multiplier("tech_tree")
    points = base_points * multiplier
    return ActivityDetails(
        consumable_points=Decimal("0"),
        repeatable_points=points,
        inputs=("Фиксированный расчёт без расхода ресурсов пользователя",),
        calculations=(
            f"Технология V уровня: "
            f"{format_calculation_number(FIFTH_TIER_TECHNOLOGY_POINTS)} очков",
            f"Технология IV уровня: "
            f"{format_calculation_number(FOURTH_TIER_TECHNOLOGY_POINTS)} очков",
            f"{format_calculation_number(FIFTH_TIER_TECHNOLOGY_POINTS)} + "
            f"{format_calculation_number(FOURTH_TIER_TECHNOLOGY_POINTS)} = "
            f"{format_calculation_number(base_points)} очков",
            f"Бонус клана за дерево технологий: × "
            f"{format_calculation_number(multiplier)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def calculate_technology_points(user: UserData) -> Decimal:
    return explain_technology_points(user).points
