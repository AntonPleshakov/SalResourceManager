from decimal import Decimal

from resources.user_data import UserData

FIFTH_TIER_TECHNOLOGY_POINTS = 163_260
FOURTH_TIER_TECHNOLOGY_POINTS = 86_040


def calculate_technology_points(_: UserData) -> Decimal:
    return Decimal(FIFTH_TIER_TECHNOLOGY_POINTS + FOURTH_TIER_TECHNOLOGY_POINTS)
