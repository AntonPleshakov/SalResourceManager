from decimal import Decimal

from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war import WarPointsCalculator
import tg.war as war


def clan_ranking(
    clan_id: int, technologies: ClanTechnologies,
) -> list[tuple[int, UserData, Decimal]]:
    calculator = WarPointsCalculator(technologies)
    scores = [
        (user, calculator.calculate([user], war.WAR_STAGES).total)
        for user in war.get_user_data_db().get_clan_users(clan_id)
    ]
    scores.sort(key=lambda item: (-item[1], str(item[0].tag.value), item[0].account_id.value))
    result = []
    previous = None
    rank = 0
    for index, (user, points) in enumerate(scores, start=1):
        if points != previous:
            rank = index
        result.append((rank, user, points))
        previous = points
    return result
