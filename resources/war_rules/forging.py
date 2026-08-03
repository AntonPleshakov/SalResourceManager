from decimal import Decimal
from typing import List, Sequence

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number

FORGE_WEAPON_CHANCES: List[List[Decimal]] = [
    [Decimal("100.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("99.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("98.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("96.00"), Decimal("4.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("91.50"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("82.00"), Decimal("16.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("64.00"), Decimal("32.00"), Decimal("4.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("27.80"), Decimal("64.00"), Decimal("8.00"), Decimal("0.20"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("13.00"), Decimal("70.00"), Decimal("16.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("6.00"), Decimal("60.00"), Decimal("32.00"), Decimal("2.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("31.90"), Decimal("64.00"), Decimal("4.00"), Decimal("0.10"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("27.50"), Decimal("64.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("8.00"), Decimal("75.00"), Decimal("16.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("66.00"), Decimal("32.00"), Decimal("2.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("31.70"), Decimal("64.00"), Decimal("4.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("21.50"), Decimal("70.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("82.90"), Decimal("16.00"), Decimal("1.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("65.70"), Decimal("32.00"), Decimal("2.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("31.50"), Decimal("64.00"), Decimal("4.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("91.00"), Decimal("8.00"), Decimal("1.00"), Decimal("0.05"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("81.70"), Decimal("16.00"), Decimal("2.00"), Decimal("0.25"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("63.50"), Decimal("32.00"), Decimal("4.00"), Decimal("0.50"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("27.00"), Decimal("64.00"), Decimal("8.00"), Decimal("1.00"), Decimal("0.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("82.00"), Decimal("16.00"), Decimal("2.00"), Decimal("0.02"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("64.00"), Decimal("32.00"), Decimal("4.00"), Decimal("0.05"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("43.80"), Decimal("50.00"), Decimal("6.00"), Decimal("0.25"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("31.50"), Decimal("60.00"), Decimal("8.00"), Decimal("0.50"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("21.00"), Decimal("65.00"), Decimal("13.00"), Decimal("1.00"), Decimal("0.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("6.99"), Decimal("68.00"), Decimal("23.00"), Decimal("2.00"), Decimal("0.02")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("60.00"), Decimal("36.00"), Decimal("4.00"), Decimal("0.05")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("50.80"), Decimal("43.00"), Decimal("6.00"), Decimal("0.25")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("41.50"), Decimal("50.00"), Decimal("8.00"), Decimal("0.50")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("28.00"), Decimal("58.00"), Decimal("13.00"), Decimal("1.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("11.00"), Decimal("64.00"), Decimal("23.00"), Decimal("2.00")],
    [Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("60.00"), Decimal("36.00"), Decimal("4.00")],
]


def forge_weapon_chances(forge_level: int) -> Sequence[Decimal]:
    if not 1 <= forge_level <= len(FORGE_WEAPON_CHANCES):
        raise ValueError(f"Unknown forge level: {forge_level}")
    return FORGE_WEAPON_CHANCES[forge_level - 1]


def weapon_points(weapon_index: int) -> int:
    if not 0 <= weapon_index < 10:
        raise ValueError(f"Unknown weapon index: {weapon_index}")
    if weapon_index <= 2:
        return 2
    if weapon_index <= 5:
        return 4
    return 5


def _expected_points_per_hammer(forge_level: int) -> Decimal:
    chances = forge_weapon_chances(forge_level)
    return sum(
        Decimal(str(chance)) * weapon_points(weapon_index) / Decimal("100")
        for weapon_index, chance in enumerate(chances)
    )


def explain_forging_points(user: UserData) -> ActivityDetails:
    expected_points = _expected_points_per_hammer(user.forge_level.value)
    points = Decimal(user.hammers.value) * expected_points
    return ActivityDetails(
        points=points,
        inputs=(
            f"Молотки: {format_calculation_number(user.hammers.value)}",
            f"Уровень кузницы: {user.forge_level.value}",
        ),
        calculations=(
            "Средние очки за один молоток с учётом шансов оружия: "
            f"{format_calculation_number(expected_points)}",
            f"{format_calculation_number(user.hammers.value)} × "
            f"{format_calculation_number(expected_points)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def calculate_forging_points(user: UserData) -> Decimal:
    return explain_forging_points(user).points
