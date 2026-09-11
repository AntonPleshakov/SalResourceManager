from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace

import pytest
from telebot.types import CallbackQuery, Chat, Message, User

from db.access_group import AccessGroupDB
from db.database import Database
from resources.clan_technology_calculator import (
    rank_clan_technology_upgrades,
)
from resources.clan_technologies import (
    CLAN_TECHNOLOGY_BY_NAME,
    CLAN_TECHNOLOGY_DEFINITIONS,
    ClanTechnologies,
    validate_clan_technology_level,
)
from resources.user_data import UserData
from resources.war import WarActivity, WarPointsCalculator
from resources.war_rules.dungeons import DUNGEON_POINTS_PER_RUN, DUNGEON_RUNS
from resources.war_rules.skills import (
    SKILL_AVERAGE_DUPLICATES_PER_UPGRADE,
    SKILL_AVERAGE_INITIAL_COUNT,
    SKILL_BASE_TICKET_COST,
    SKILL_CREATION_POINTS,
    SKILL_UPGRADE_POINTS,
)
from tests.handler_context import clan_admin_context
from tg.admins.clan_technologies import (
    clan_technology_calculator,
    request_clan_technology_level,
    save_clan_technology_level,
    set_max_clan_technology_level,
)


def make_callback(data: str) -> CallbackQuery:
    user = User(42, False, "Admin", username="admin")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def make_message(text: str) -> Message:
    user = User(42, False, "Admin", username="admin")
    return Message(
        2,
        user,
        0,
        Chat(42, "private"),
        "text",
        {"text": text},
        None,
    )


def callback_data(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
    ]


class ClanTechnologyBot:
    def __init__(self):
        self.data = {}
        self.deleted_messages = []
        self.deleted_states = []
        self.edits = []

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def answer_callback_query(self, *args, **kwargs):
        pass

    def delete_message(self, chat_id, message_id):
        self.deleted_messages.append((chat_id, message_id))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def edit_message_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def send_message(self, *args, **kwargs):
        raise AssertionError("Successful input must reuse the prompt message")

    def set_state(self, user_id, state):
        pass


def test_clan_technology_catalog_matches_supplied_tables():
    assert len(CLAN_TECHNOLOGY_DEFINITIONS) == 21
    assert {
        definition.flask_cost for definition in CLAN_TECHNOLOGY_DEFINITIONS[:10]
    } == {486}
    assert {
        definition.flask_cost for definition in CLAN_TECHNOLOGY_DEFINITIONS[10:16]
    } == {810}
    assert CLAN_TECHNOLOGY_BY_NAME["clan_war_damage"].max_level == 100
    assert CLAN_TECHNOLOGY_BY_NAME["personal_rewards"].increase_percent == 1
    assert all(
        definition.flask_cost == 3_244
        for definition in CLAN_TECHNOLOGY_DEFINITIONS[-3:]
    )


def test_clan_technology_levels_are_stored_per_clan(tmp_path):
    database = Database(tmp_path / "clans.db")
    groups = AccessGroupDB(database)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")

    updated = groups.set_clan_technology(
        -100001, "forging_equipment", 7
    )

    assert updated.forging_equipment == 7
    assert groups.get_clan_technologies(-100001).forging_equipment == 7
    assert groups.get_clan_technologies(-100002) == ClanTechnologies()


def test_clan_technology_level_validation_uses_each_maximum():
    assert validate_clan_technology_level("clan_war_damage", 100) == 100
    with pytest.raises(ValueError, match="от 0 до 10"):
        validate_clan_technology_level("clan_war_day_1", 11)


def test_activity_and_day_bonuses_are_multiplied_for_every_account():
    technologies = ClanTechnologies(dungeon_keys=2, clan_war_day_1=3)
    users = [UserData(user_id=1), UserData(user_id=2)]

    report = WarPointsCalculator(technologies).calculate(
        users, {1: (WarActivity.DUNGEONS,)}
    )

    base = Decimal(DUNGEON_RUNS * DUNGEON_POINTS_PER_RUN)
    expected = base * Decimal("1.08") * Decimal("1.12") * 2
    assert report.points_by_day == {1: expected}
    assert report.total == expected


def test_skill_summon_and_upgrade_bonuses_apply_to_separate_parts():
    user = UserData(skills=4_000)
    technologies = ClanTechnologies(
        summoning_skills=1,
        upgrading_skills=2,
    )
    details = WarPointsCalculator(technologies).calculate_details(
        user, [WarActivity.SKILLS]
    )[WarActivity.SKILLS]

    summons = Decimal(user.skills.value) / SKILL_BASE_TICKET_COST
    upgrades = max(
        summons - SKILL_AVERAGE_INITIAL_COUNT, Decimal("0")
    ) / SKILL_AVERAGE_DUPLICATES_PER_UPGRADE
    expected = (
        summons * SKILL_CREATION_POINTS * Decimal("1.04")
        + upgrades * SKILL_UPGRADE_POINTS * Decimal("1.08")
    )
    assert details.points == expected


def test_combat_and_reward_technologies_do_not_change_points():
    user = UserData(skills=4_000)
    technologies = ClanTechnologies(
        clan_war_damage=100,
        clan_war_health=100,
        personal_rewards=10,
        win_rewards=10,
        lose_rewards=10,
    )
    stages = {1: (WarActivity.SKILLS,)}

    baseline = WarPointsCalculator().calculate([user], stages)
    configured = WarPointsCalculator(technologies).calculate([user], stages)

    assert configured == baseline


def test_upgrade_calculator_ranks_marginal_points_per_flask():
    users = [UserData(user_id=1)]
    stages = {
        1: (
            WarActivity.TECHNOLOGIES,
            WarActivity.TECHNOLOGIES,
            WarActivity.TECHNOLOGIES,
        )
    }

    recommendations = rank_clan_technology_upgrades(
        users,
        ClanTechnologies(),
        stages,
    )

    assert recommendations[0].definition.name == "tech_tree"
    assert recommendations[0].points_gain > 0
    assert recommendations[0].max_points_gain == (
        recommendations[0].points_gain * 10
    )
    assert recommendations[0].levels_to_max == 10
    assert recommendations[0].flasks_to_max == 4_860
    assert recommendations[0].points_per_flask > (
        recommendations[1].points_per_flask
    )
    assert recommendations[-1].points_gain == 0


def test_upgrade_calculator_skips_maxed_technologies():
    recommendations = rank_clan_technology_upgrades(
        [UserData(user_id=1)],
        ClanTechnologies(tech_tree=10),
        {1: (WarActivity.TECHNOLOGIES,) * 3},
    )

    assert "tech_tree" not in {
        recommendation.definition.name
        for recommendation in recommendations
    }


def test_upgrade_calculator_only_recalculates_each_next_level(monkeypatch):
    calculations = []

    class CalculatorStub:
        def __init__(self, technologies):
            self.technologies = technologies

        def calculate(self, users, stages):
            calculations.append(self.technologies)
            return SimpleNamespace(
                total=Decimal(sum(self.technologies.values()))
            )

    monkeypatch.setattr(
        "resources.clan_technology_calculator.WarPointsCalculator",
        CalculatorStub,
    )

    recommendations = rank_clan_technology_upgrades(
        [UserData(user_id=1)],
        ClanTechnologies(),
        {},
    )

    assert len(calculations) == len(recommendations) + 1


def test_level_input_has_cancel_and_max_buttons_and_returns_to_grid(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "clan-input.db")
    groups = AccessGroupDB(database)
    groups.add_group(-100123, "Test clan")
    monkeypatch.setattr(
        "tg.admins.clan_technologies.get_access_group_db", lambda: groups
    )
    bot = ClanTechnologyBot()
    callback = make_callback(
        "admins/clan_technologies/edit/forging_equipment"
    )

    request_clan_technology_level(clan_admin_context(callback, bot))

    keyboard = bot.edits[0][1]["reply_markup"]
    assert [button.text for row in keyboard.keyboard for button in row] == [
        "✖️ Отмена",
        "⬆️ Максимальный уровень",
    ]

    message = make_message("5")
    save_clan_technology_level(clan_admin_context(message, bot))

    assert groups.get_clan_technologies(-100123).forging_equipment == 5
    assert bot.deleted_messages == [(42, 2)]
    assert bot.edits[-1][1]["message_id"] == 1
    assert "уровень 5 — сохранено" in bot.edits[-1][1]["rich_message"].html
    markup = bot.edits[-1][1]["reply_markup"]
    assert callback_data(markup) == [
        *(
            f"admins/clan_technologies/edit/{definition.name}"
            for definition in CLAN_TECHNOLOGY_DEFINITIONS
            if definition.affects_war_points
        ),
        "admins/clan_technologies/calculator",
        "admins",
        "home",
    ]
    assert markup.keyboard[0][0].text == "⚒️ 5 / 10"
    assert "<tg-button" not in bot.edits[-1][1]["rich_message"].html


def test_max_level_button_saves_max_and_returns_to_grid(tmp_path, monkeypatch):
    database = Database(tmp_path / "clan-max.db")
    groups = AccessGroupDB(database)
    groups.add_group(-100123, "Test clan")
    monkeypatch.setattr(
        "tg.admins.clan_technologies.get_access_group_db", lambda: groups
    )
    bot = ClanTechnologyBot()
    request = make_callback(
        "admins/clan_technologies/edit/forging_equipment"
    )
    request_clan_technology_level(clan_admin_context(request, bot))
    maximum = make_callback(
        "admins/clan_technologies/max/forging_equipment"
    )

    set_max_clan_technology_level(clan_admin_context(maximum, bot))

    assert groups.get_clan_technologies(-100123).forging_equipment == 10
    rich_message = bot.edits[-1][1]["rich_message"]
    assert "уровень Max — сохранено" in rich_message.html
    markup = bot.edits[-1][1]["reply_markup"]
    assert markup.keyboard[0][0].text == "⚒️ Max"


def test_clan_technology_calculator_uses_selected_clan_data(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "clan-calculator.db")
    groups = AccessGroupDB(database)
    groups.add_group(-100123, "Test clan")
    users = [UserData(user_id=1)]
    monkeypatch.setattr(
        "tg.admins.clan_technologies.get_access_group_db", lambda: groups
    )
    monkeypatch.setattr(
        "tg.admins.clan_technologies.get_user_data_db",
        lambda: type(
            "UserDataStub",
            (),
            {"get_clan_users": lambda _, group_id: users},
        )(),
    )
    bot = ClanTechnologyBot()
    callback = make_callback("admins/clan_technologies/calculator")

    clan_technology_calculator(clan_admin_context(callback, bot))

    rich_message = bot.edits[-1][1]["rich_message"]
    assert "Выгоднее всего сейчас" in rich_message.html
    assert "Очков/колбу" in rich_message.html
    assert "За 1 уровень" in rich_message.html
    assert "До Max" in rich_message.html
    assert "<th>Уровень</th>" not in rich_message.html
    assert "ур. ·" in rich_message.html
    assert "/🧪" in rich_message.html
    assert "аккаунтов клана (1)" in rich_message.html
    assert "admins/clan_technologies" in rich_message.html
