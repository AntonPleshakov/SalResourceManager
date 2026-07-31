from decimal import Decimal

from resources.user_data import UserData


def calculate_dungeon_points(_: UserData) -> Decimal:
    return Decimal(4200 * 8)
