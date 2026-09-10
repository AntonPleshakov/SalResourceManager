from dataclasses import dataclass, fields
from decimal import Decimal


@dataclass(frozen=True)
class ClanTechnologyDefinition:
    name: str
    title: str
    ability: str
    increase_percent: int
    max_level: int
    flask_cost: int
    icon: str
    affects_war_points: bool = True


CLAN_TECHNOLOGY_DEFINITIONS = (
    ClanTechnologyDefinition(
        "forging_equipment",
        "Ковка снаряжения",
        "Очки за ковку снаряжения",
        4, 10, 486, "⚒️",
    ),
    ClanTechnologyDefinition(
        "summoning_skills", "Призыв навыков", "Очки за призыв навыков",
        4, 10, 486, "🟢",
    ),
    ClanTechnologyDefinition(
        "upgrading_skills", "Улучшение навыков", "Очки за улучшение навыков",
        4, 10, 486, "⬆️",
    ),
    ClanTechnologyDefinition(
        "tech_tree", "Дерево технологий", "Очки за улучшение технологий",
        4, 10, 486, "🔬",
    ),
    ClanTechnologyDefinition(
        "forge_upgrades", "Улучшение кузницы", "Очки за траты в кузнице",
        4, 10, 486, "🔥",
    ),
    ClanTechnologyDefinition(
        "dungeon_keys", "Ключи подземелий", "Очки за использование ключей",
        4, 10, 486, "🗝️",
    ),
    ClanTechnologyDefinition(
        "hatching_eggs", "Вылупление яиц", "Очки за вылупление яиц",
        4, 10, 486, "🥚",
    ),
    ClanTechnologyDefinition(
        "merging_pets", "Объединение питомцев", "Очки за объединение питомцев",
        4, 10, 486, "🐾",
    ),
    ClanTechnologyDefinition(
        "summoning_mounts", "Призыв маунтов", "Очки за призыв маунтов",
        4, 10, 486, "🐴",
    ),
    ClanTechnologyDefinition(
        "merging_mounts", "Объединение маунтов", "Очки за объединение маунтов",
        4, 10, 486, "🔄",
    ),
    *(
        ClanTechnologyDefinition(
            f"clan_war_day_{day}",
            f"День войны {day}",
            f"Все очки в день войны {day}",
            4,
            10,
            810,
            f"{day}️⃣",
        )
        for day in range(1, 7)
    ),
    ClanTechnologyDefinition(
        "clan_war_damage", "Урон в войне", "Урон атак и потасовок",
        100, 100, 492, "⚔️", False,
    ),
    ClanTechnologyDefinition(
        "clan_war_health", "Здоровье в войне", "Здоровье атак и потасовок",
        100, 100, 492, "❤️", False,
    ),
    ClanTechnologyDefinition(
        "personal_rewards", "Личные награды", "Личные награды войны",
        1, 10, 3_244, "🎁", False,
    ),
    ClanTechnologyDefinition(
        "win_rewards", "Награды за победу", "Награды за победу в войне",
        1, 10, 3_244, "🏆", False,
    ),
    ClanTechnologyDefinition(
        "lose_rewards", "Награды за поражение", "Награды за поражение в войне",
        1, 10, 3_244, "🎒", False,
    ),
)
CLAN_TECHNOLOGY_BY_NAME = {
    definition.name: definition
    for definition in CLAN_TECHNOLOGY_DEFINITIONS
}


@dataclass(frozen=True)
class ClanTechnologies:
    forging_equipment: int = 0
    summoning_skills: int = 0
    upgrading_skills: int = 0
    tech_tree: int = 0
    forge_upgrades: int = 0
    dungeon_keys: int = 0
    hatching_eggs: int = 0
    merging_pets: int = 0
    summoning_mounts: int = 0
    merging_mounts: int = 0
    clan_war_day_1: int = 0
    clan_war_day_2: int = 0
    clan_war_day_3: int = 0
    clan_war_day_4: int = 0
    clan_war_day_5: int = 0
    clan_war_day_6: int = 0
    clan_war_damage: int = 0
    clan_war_health: int = 0
    personal_rewards: int = 0
    win_rewards: int = 0
    lose_rewards: int = 0

    def values(self) -> tuple[int, ...]:
        return tuple(getattr(self, field.name) for field in fields(self))

    def multiplier(self, name: str) -> Decimal:
        definition = CLAN_TECHNOLOGY_BY_NAME[name]
        level = getattr(self, name)
        return Decimal("1") + (
            Decimal(level * definition.increase_percent) / Decimal("100")
        )

    def day_multiplier(self, day: int) -> Decimal:
        name = f"clan_war_day_{day}"
        if name not in CLAN_TECHNOLOGY_BY_NAME:
            return Decimal("1")
        return self.multiplier(name)


def validate_clan_technology_level(name: str, level: int) -> int:
    definition = CLAN_TECHNOLOGY_BY_NAME.get(name)
    if definition is None:
        raise ValueError("Клановая технология не найдена")
    if not isinstance(level, int) or not 0 <= level <= definition.max_level:
        raise ValueError(
            f"Уровень технологии должен быть от 0 до {definition.max_level}"
        )
    return level
