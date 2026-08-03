from decimal import Decimal

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


DUNGEON_RUNS = 8
DUNGEON_POINTS_PER_RUN = 4_200


def explain_dungeon_points(_: UserData) -> ActivityDetails:
    points = Decimal(DUNGEON_RUNS * DUNGEON_POINTS_PER_RUN)
    return ActivityDetails(
        points=points,
        inputs=(f"Прохождения подземелий: {DUNGEON_RUNS}",),
        calculations=(
            f"{DUNGEON_RUNS} прохождений × "
            f"{format_calculation_number(DUNGEON_POINTS_PER_RUN)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )


def calculate_dungeon_points(user: UserData) -> Decimal:
    return explain_dungeon_points(user).points
