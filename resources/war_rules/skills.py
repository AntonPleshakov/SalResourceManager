from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


SKILL_TICKET_POINTS = Decimal("225")
SKILL_UPGRADE_POINTS = Decimal("175")
SKILL_BASE_TICKET_COST = Decimal("40")
SKILL_AVERAGE_DUPLICATES_PER_UPGRADE = Decimal("5")
SKILL_SYSTEM_DISTRIBUTION: Tuple[Tuple[Decimal, int], ...] = (
    (Decimal("0.90"), 18),
    (Decimal("0.09"), 15),
    (Decimal("0.01"), 12),
)
SKILL_AVERAGE_INITIAL_COUNT = sum(
    share * skill_count for share, skill_count in SKILL_SYSTEM_DISTRIBUTION
)


def explain_skill_points(user: UserData) -> ActivityDetails:
    tickets = Decimal(user.skills.value)
    discount = Decimal(user.skill_summon_cost.value)
    ticket_cost = SKILL_BASE_TICKET_COST * (Decimal("100") - discount) / Decimal("100")
    summoned_skills = tickets / ticket_cost
    expected_upgrades = max(
        summoned_skills - SKILL_AVERAGE_INITIAL_COUNT, Decimal("0")
    ) / SKILL_AVERAGE_DUPLICATES_PER_UPGRADE
    ticket_points = tickets * SKILL_TICKET_POINTS
    upgrade_points = expected_upgrades * SKILL_UPGRADE_POINTS
    points = ticket_points + upgrade_points
    return ActivityDetails(
        points=points,
        inputs=(
            f"Билетики навыков: {format_calculation_number(tickets)}",
            f"Снижение стоимости призыва: {format_calculation_number(discount)}%",
        ),
        calculations=(
            f"Цена призыва: {format_calculation_number(SKILL_BASE_TICKET_COST)} × "
            f"(100 − {format_calculation_number(discount)})% = "
            f"{format_calculation_number(ticket_cost)} билетика",
            f"Ожидаемые призывы: {format_calculation_number(tickets)} ÷ "
            f"{format_calculation_number(ticket_cost)} = "
            f"{format_calculation_number(summoned_skills)}",
            f"Ожидаемые улучшения: max(призывы − "
            f"{format_calculation_number(SKILL_AVERAGE_INITIAL_COUNT)}, 0) ÷ "
            f"{format_calculation_number(SKILL_AVERAGE_DUPLICATES_PER_UPGRADE)} = "
            f"{format_calculation_number(expected_upgrades)}",
            f"За билетики: {format_calculation_number(tickets)} × "
            f"{format_calculation_number(SKILL_TICKET_POINTS)} = "
            f"{format_calculation_number(ticket_points)} очков",
            f"За улучшения: {format_calculation_number(expected_upgrades)} × "
            f"{format_calculation_number(SKILL_UPGRADE_POINTS)} = "
            f"{format_calculation_number(upgrade_points)} очков",
            f"Итого: {format_calculation_number(ticket_points)} + "
            f"{format_calculation_number(upgrade_points)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def calculate_skill_points(user: UserData) -> Decimal:
    return explain_skill_points(user).points
