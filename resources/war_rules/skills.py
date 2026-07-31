from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData


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


def calculate_skill_points(user: UserData) -> Decimal:
    tickets = Decimal(user.skills.value)
    discount = Decimal(user.skill_summon_cost.value)
    ticket_cost = SKILL_BASE_TICKET_COST * (Decimal("100") - discount) / Decimal("100")
    summoned_skills = tickets / ticket_cost
    expected_upgrades = max(
        summoned_skills - SKILL_AVERAGE_INITIAL_COUNT, Decimal("0")
    ) / SKILL_AVERAGE_DUPLICATES_PER_UPGRADE
    return tickets * SKILL_TICKET_POINTS + expected_upgrades * SKILL_UPGRADE_POINTS
