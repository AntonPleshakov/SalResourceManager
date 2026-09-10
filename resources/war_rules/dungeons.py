from decimal import Decimal

from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


DUNGEON_RUNS = 8
DUNGEON_POINTS_PER_RUN = 4_200


def explain_dungeon_points(
    _: UserData,
    clan_technologies: ClanTechnologies = ClanTechnologies(),
) -> ActivityDetails:
    base_points = Decimal(DUNGEON_RUNS * DUNGEON_POINTS_PER_RUN)
    multiplier = clan_technologies.multiplier("dungeon_keys")
    points = base_points * multiplier
    return ActivityDetails(
        consumable_points=Decimal("0"),
        repeatable_points=points,
        inputs=(f"Прохождения подземелий: {DUNGEON_RUNS}",),
        calculations=(
            f"{DUNGEON_RUNS} прохождений × "
            f"{format_calculation_number(DUNGEON_POINTS_PER_RUN)} = "
            f"{format_calculation_number(base_points)} очков",
            f"Бонус клана за ключи подземелий: × "
            f"{format_calculation_number(multiplier)} = "
            f"{format_calculation_number(points)} очков",
        ),
    )
