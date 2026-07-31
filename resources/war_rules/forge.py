from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData


FORGE_POINTS_PER_THOUSAND_COINS = 38
FORGE_RESET_UPGRADES = 8
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


def calculate_forge_points(user: UserData) -> Decimal:
    forge_level = user.forge_level.value
    if forge_level == len(FORGE_TOTAL_COSTS):
        total_cost = sum(FORGE_TOTAL_COSTS[1 : FORGE_RESET_UPGRADES + 1])
    else:
        total_cost = FORGE_TOTAL_COSTS[forge_level]
    return Decimal(total_cost // 1_000 * FORGE_POINTS_PER_THOUSAND_COINS)
