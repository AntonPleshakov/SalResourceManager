from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

import resources.user_data as user_data_resources
from db.database import Database
from db.user_data import UserDataDB
from resources.egg_levels import EGG_LEVELS, EggLevel
from resources.user_data import (
    EDITABLE_FIELDS,
    UserData,
    parse_editable_field_value,
    parse_non_negative_int,
)
from resources.war import WarActivity, WarPointsCalculator
from resources.war_rules.forge import calculate_forge_points
from resources.war_rules.forging import (
    FORGE_WEAPON_CHANCES,
    forge_weapon_chances,
    weapon_points,
)
from resources.war_rules.mounts import calculate_mount_points
from resources.war_rules.pets import calculate_pet_points, explain_pet_points
from resources.war_rules.technologies import calculate_technology_points
from tg.utils import format_points
from tg.user_data import (
    _get_group_tag,
    _value_input_hint,
    fill_tracked_fields,
    request_value,
    save_fill_value,
    save_value,
)
from tg.user_data.common import ensure_active_user
from tg.user_data.fill import skip_fill_value


def make_callback(data: str) -> CallbackQuery:
    user = User(42, False, "Tester", username="tester")
    chat = Chat(42, "private")
    message = Message(1, user, 0, chat, "text", {"text": "reminder"}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def test_user_data_round_trip():
    original = UserData(
        user_id=42,
        username="tester",
        tag="Лидер",
        mount_keys=1,
        skills=2,
        shells=3,
        hammers=4,
        pets=5,
        unmerged_mounts=6,
        skill_summon_cost=8,
        extra_egg_chance=9,
        mount_summon_cost=10,
        extra_mount_chance=11,
    )

    restored = UserData.from_row(original.to_row())

    assert restored == original
    assert restored.tag.value == "Лидер"
    header = original.params_views()
    assert header[header.index("Telegram username") + 1] == "Имя игрового аккаунта"
    assert set(EDITABLE_FIELDS) == {
        "mount_keys",
        "skills",
        "shells",
        "hammers",
        "pets",
        "unmerged_mounts",
        "forge_level",
        "skill_summon_cost",
        "extra_egg_chance",
        "mount_summon_cost",
        "extra_mount_chance",
        "eggs_per_hatch_batch",
        "max_egg_level",
        "hatch_batches_common",
        "hatch_batches_rare",
        "hatch_batches_epic",
        "hatch_batches_legendary",
        "hatch_batches_ultimate",
        "hatch_batches_mythic",
    }


def test_group_tag_is_taken_from_chat_member_tag(monkeypatch):
    class FakeAccessGroupDB:
        def get_group_id(self):
            return -100123

    class FakeBot:
        def get_chat_member(self, group_id, user_id):
            assert group_id == -100123
            assert user_id == 42
            return type("Member", (), {"tag": "Лидер"})()

    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: FakeAccessGroupDB()
    )

    assert _get_group_tag(FakeBot(), 42) == "Лидер"


def test_group_tag_prefers_chat_member_custom_title(monkeypatch):
    class FakeAccessGroupDB:
        def get_group_id(self):
            return -100123

    class FakeBot:
        def get_chat_member(self, _group_id, _user_id):
            return type(
                "Member", (), {"custom_title": "Офицер", "tag": "Лидер"}
            )()

    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: FakeAccessGroupDB()
    )

    assert _get_group_tag(FakeBot(), 42) == "Офицер"


def test_first_game_account_is_created_from_group_tag(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    class FakeAccessGroupDB:
        def get_group_id(self):
            return -100123

    class FakeBot:
        def get_chat_member(self, group_id, user_id):
            assert (group_id, user_id) == (-100123, 42)
            return SimpleNamespace(custom_title="Лидер")

    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: FakeAccessGroupDB()
    )

    result = ensure_active_user(make_callback("home"), FakeBot())

    assert result.is_new_user is True
    assert result.group_tag_found is True
    assert result.user.tag.value == "Лидер"
    assert [account.tag for account in database.get_accounts(42)] == ["Лидер"]
    connection.close()


def test_first_game_account_uses_username_when_group_tag_is_missing(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    class FakeAccessGroupDB:
        def get_group_id(self):
            return None

    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: FakeAccessGroupDB()
    )

    result = ensure_active_user(make_callback("home"), object())

    assert result.is_new_user is True
    assert result.group_tag_found is False
    assert result.user.tag.value == "tester"
    assert [account.tag for account in database.get_accounts(42)] == ["tester"]
    connection.close()


def test_existing_account_is_returned_as_an_existing_user(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)
    database.add_account(42, "old_username", "Лидер")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)

    result = ensure_active_user(make_callback("home"), object())

    assert result.is_new_user is False
    assert result.group_tag_found is None
    assert result.user.tag.value == "Лидер"
    assert result.user.username.value == "tester"
    connection.close()


def test_database_creates_and_updates_user(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    created = database.get_or_create(42, "tester")
    updated = database.set_value(
        42, "tester", "pets", 1500, updated_on=date(2026, 8, 2)
    )

    assert created.user_id.value == updated.user_id.value
    assert updated.pets.value == 1500
    assert updated.get_updated_on("pets") == date(2026, 8, 2)
    assert database.get_user(42).pets.value == 1500
    connection.close()


def test_database_loads_existing_users(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)
    database.set_value(42, "tester", "pets", 12)

    loaded = database.get_user(42)

    assert loaded is not None
    assert loaded.pets.value == 12
    connection.close()


def test_database_saves_multiple_fields_in_one_update(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    updated = database.set_values(
        42,
        "tester",
        {"hammers": 1500, "pets": 3, "extra_mount_chance": 10},
        updated_on=date(2026, 8, 2),
    )

    assert updated.hammers.value == 1500
    assert updated.pets.value == 3
    assert updated.extra_mount_chance.value == 10
    assert updated.get_updated_on("hammers") == date(2026, 8, 2)
    assert updated.get_updated_on("pets") == date(2026, 8, 2)
    assert updated.get_updated_on("extra_mount_chance") == date(2026, 8, 2)
    connection.close()


def test_user_rows_preserve_blank_update_dates():
    user = UserData(user_id=42, username="tester", pets=100)
    restored = UserData.from_row(user.to_row())

    assert restored.pets.value == 100
    assert restored.get_updated_on("pets") is None


def test_updating_technology_marks_its_own_update_date(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    user = database.set_value(
        42,
        "tester",
        "forge_level",
        10,
        updated_on=date(2026, 8, 2),
    )

    assert user.get_updated_on("forge_level") == date(2026, 8, 2)
    assert user.get_updated_on("mount_keys") is None
    connection.close()


def test_database_rejects_unknown_forge_level(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    try:
        database.set_value(42, "tester", "forge_level", 36)
    except ValueError as error:
        assert str(error) == "Уровень кузницы должен быть от 1 до 35"
    else:
        raise AssertionError("Forge level above 35 must be rejected")
    connection.close()


def test_database_rejects_excessive_skill_summon_cost_reduction(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    try:
        database.set_value(42, "tester", "skill_summon_cost", 26)
    except ValueError as error:
        assert str(error) == (
            "Снижение стоимости призыва навыков должно быть от 0 до 25%"
        )
    else:
        raise AssertionError("Skill summon cost reduction above 25 must be rejected")
    connection.close()


def test_database_rejects_excessive_mount_summon_cost_reduction(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    try:
        database.set_value(42, "tester", "mount_summon_cost", 26)
    except ValueError as error:
        assert str(error) == (
            "Снижение стоимости призыва маунта должно быть от 0 до 25%"
        )
    else:
        raise AssertionError("Mount summon cost reduction above 25 must be rejected")
    connection.close()


def test_database_rejects_excessive_extra_mount_chance(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    try:
        database.set_value(42, "tester", "extra_mount_chance", 51)
    except ValueError as error:
        assert str(error) == (
            "Шанс на дополнительного маунта должен быть от 0 до 50%"
        )
    else:
        raise AssertionError("Extra mount chance above 50 must be rejected")
    connection.close()


def test_eggs_per_hatch_batch_accepts_only_two_to_four(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)

    for value in (1, 5):
        try:
            database.set_value(42, "tester", "eggs_per_hatch_batch", value)
        except ValueError as error:
            assert str(error) == (
                "Количество яиц в одном пакете должно быть от 2 до 4"
            )
        else:
            raise AssertionError(f"{value} eggs per batch must be rejected")

    assert database.set_value(
        42, "tester", "eggs_per_hatch_batch", 2
    ).eggs_per_hatch_batch.value == 2
    connection.close()


def test_forge_chance_matrix_has_35_levels_and_ten_weapon_levels():
    assert len(FORGE_WEAPON_CHANCES) == 35
    assert all(len(chances) == 10 for chances in FORGE_WEAPON_CHANCES)
    assert forge_weapon_chances(1) == [100] + [0] * 9
    assert forge_weapon_chances(35) == [0, 0, 0, 0, 0, 0, 0, 60, 36, 4]


def test_war_points_calculator_applies_fixed_forging_rule():
    user = UserData(user_id=42, forge_level=1, hammers=3)

    assert weapon_points(2) == 2
    assert weapon_points(3) == 4
    assert weapon_points(9) == 5
    report = WarPointsCalculator().calculate(
        [user], {1: (WarActivity.FORGING,)}
    )

    assert report.points_by_day == {1: 6}
    assert report.points_by_activity_by_day == {
        1: {WarActivity.FORGING: 6}
    }
    assert report.total == 6


def test_war_points_calculator_reports_each_activity_separately():
    user = UserData(user_id=42, forge_level=1, hammers=3)

    report = WarPointsCalculator().calculate(
        [user],
        {
            1: (
                WarActivity.FORGING,
                WarActivity.DUNGEONS,
                WarActivity.FORGING,
            )
        },
    )

    assert report.points_by_activity_by_day == {
        1: {
            WarActivity.FORGING: 12,
            WarActivity.DUNGEONS: 33_600,
        }
    }
    assert report.points_by_activity == {
        WarActivity.FORGING: 6,
        WarActivity.DUNGEONS: 33_600,
    }
    assert report.points_by_day == {1: 33_612}
    assert report.total == 33_606


def test_consumable_activity_scores_once_and_repeatable_activity_scores_each_time():
    user = UserData(
        user_id=42,
        mount_keys=2_500,
        mount_summon_cost=0,
        extra_mount_chance=0,
        unmerged_mounts=0,
    )
    stages = {
        1: (WarActivity.MOUNTS, WarActivity.TECHNOLOGIES),
        2: (WarActivity.MOUNTS, WarActivity.TECHNOLOGIES),
    }

    report = WarPointsCalculator().calculate([user], stages)
    mount_points = calculate_mount_points(user)
    technology_points = calculate_technology_points(user)

    assert report.points_by_activity_by_day == {
        1: {
            WarActivity.MOUNTS: mount_points,
            WarActivity.TECHNOLOGIES: technology_points,
        },
        2: {
            WarActivity.MOUNTS: mount_points,
            WarActivity.TECHNOLOGIES: technology_points,
        },
    }
    assert report.points_by_activity == {
        WarActivity.MOUNTS: mount_points,
        WarActivity.TECHNOLOGIES: technology_points * 2,
    }
    assert report.total == mount_points + technology_points * 2
    assert sum(report.points_by_day.values()) == (
        mount_points * 2 + technology_points * 2
    )
    assert sum(report.points_by_day.values()) > report.total


def test_pet_resources_score_once_but_daily_hatching_repeats():
    user = UserData(user_id=42, shells=100, pets=2)

    report = WarPointsCalculator().calculate(
        [user],
        {
            1: (WarActivity.PETS,),
            2: (WarActivity.PETS,),
        },
    )
    details = WarPointsCalculator().calculate_details(
        user, [WarActivity.PETS]
    )[WarActivity.PETS]

    assert report.points_by_day == {
        1: details.points,
        2: details.points,
    }
    assert report.points_by_activity == {
        WarActivity.PETS: details.consumable_points
        + details.repeatable_points * 2
    }


def test_slow_forge_scores_once_while_dungeons_repeat():
    user = UserData(user_id=42, forge_level=23)
    stages = {
        1: (WarActivity.FORGE, WarActivity.DUNGEONS),
        2: (WarActivity.FORGE, WarActivity.DUNGEONS),
    }

    report = WarPointsCalculator().calculate([user], stages)
    details = WarPointsCalculator().calculate_details(
        user,
        [WarActivity.FORGE, WarActivity.DUNGEONS],
    )

    assert report.points_by_activity == {
        WarActivity.FORGE: details[WarActivity.FORGE].points,
        WarActivity.DUNGEONS: details[WarActivity.DUNGEONS].points * 2,
    }
    assert report.points_by_activity_by_day[2][WarActivity.FORGE] == 0
    assert (
        report.points_by_activity_by_day[2][WarActivity.DUNGEONS]
        == details[WarActivity.DUNGEONS].points
    )


def test_forge_at_level_22_upgrades_before_its_second_war_day():
    user = UserData(user_id=42, forge_level=22)

    report = WarPointsCalculator().calculate(
        [user],
        {
            2: (WarActivity.FORGE,),
            4: (WarActivity.FORGE,),
        },
    )
    first_points = calculate_forge_points(user)
    second_points = calculate_forge_points(
        UserData(user_id=42, forge_level=23)
    )

    assert report.points_by_day == {
        2: first_points,
        4: second_points,
    }
    assert report.points_by_activity == {
        WarActivity.FORGE: first_points + second_points
    }


def test_forge_above_level_22_does_not_upgrade_before_second_war_day():
    user = UserData(user_id=42, forge_level=23)

    report = WarPointsCalculator().calculate(
        [user],
        {
            2: (WarActivity.FORGE,),
            4: (WarActivity.FORGE,),
        },
    )

    assert report.points_by_day == {
        2: calculate_forge_points(user),
        4: 0,
    }


def test_activity_details_match_calculated_points():
    user = UserData(
        user_id=42,
        mount_keys=2_500,
        skills=1_000,
        shells=400,
        hammers=300,
        pets=2,
        unmerged_mounts=3,
        forge_level=10,
        skill_summon_cost=10,
        extra_egg_chance=5,
        mount_summon_cost=10,
        extra_mount_chance=10,
    )
    activities = list(WarActivity)
    calculator = WarPointsCalculator()

    report = calculator.calculate(
        [user],
        {day: (activity,) for day, activity in enumerate(activities, start=1)},
    )
    details = calculator.calculate_details(user, activities)

    assert set(details) == set(activities)
    for day, activity in enumerate(activities, start=1):
        assert details[activity].points == report.points_by_day[day]
        assert details[activity].inputs
        assert details[activity].calculations


def test_war_points_calculator_applies_fixed_dungeon_rule_per_user():
    users = [UserData(user_id=1), UserData(user_id=2)]

    report = WarPointsCalculator().calculate(
        users, {1: (WarActivity.DUNGEONS,)}
    )

    assert report.points_by_day == {1: 67_200}
    assert report.total == 67_200


def test_war_points_calculator_applies_forge_upgrade_rule():
    users = [UserData(user_id=1, forge_level=5), UserData(user_id=2, forge_level=35)]

    report = WarPointsCalculator().calculate(
        users, {1: (WarActivity.FORGE,)}
    )

    assert report.points_by_day == {1: 7_638}
    assert report.total == 7_638


def test_war_points_calculator_applies_fixed_technology_rule_per_user():
    users = [UserData(user_id=1), UserData(user_id=2)]

    report = WarPointsCalculator().calculate(
        users, {1: (WarActivity.TECHNOLOGIES,)}
    )

    assert report.points_by_day == {1: 498_600}
    assert report.total == 498_600


def test_war_points_calculator_applies_mount_rule():
    user = UserData(
        user_id=1,
        mount_keys=2_075,
        mount_summon_cost=17,
        extra_mount_chance=10,
        unmerged_mounts=5,
    )

    report = WarPointsCalculator().calculate(
        [user], {1: (WarActivity.MOUNTS,)}
    )

    assert report.points_by_day == {1: 124_200}
    assert report.total == 124_200


def test_war_points_calculator_applies_pet_rule():
    user = UserData(user_id=1, shells=100, extra_egg_chance=50, pets=2)

    report = WarPointsCalculator().calculate(
        [user], {1: (WarActivity.PETS,)}
    )

    assert report.points_by_day == {1: Decimal("468675.0")}
    assert report.total == Decimal("468675.0")


def test_pet_rule_uses_batch_size_level_and_daily_batches():
    user = UserData(
        user_id=1,
        eggs_per_hatch_batch=3,
        max_egg_level=EggLevel.LEGENDARY,
        hatch_batches_common=1,
        hatch_batches_rare=2,
        hatch_batches_epic=3,
        hatch_batches_legendary=2,
        hatch_batches_ultimate=99,
        hatch_batches_mythic=99,
    )

    details = explain_pet_points(user)

    assert details.repeatable_points == 140_400
    assert details.consumable_points == 34_560
    assert calculate_pet_points(user) == 174_960
    assert any("Legendary" in value for value in details.inputs)
    assert all("99" not in value for value in details.inputs)


def test_egg_points_follow_the_configured_level_scale():
    assert tuple(level.points for level in EGG_LEVELS) == (
        720,
        2_880,
        5_760,
        11_520,
        23_040,
        46_080,
    )


def test_war_points_calculator_estimates_skill_points():
    user = UserData(user_id=42, skills=2490, skill_summon_cost=17)

    calculator = WarPointsCalculator()
    report = calculator.calculate(
        [user], {1: (WarActivity.SKILLS,)}
    )
    details = calculator.calculate_details(user, [WarActivity.SKILLS])[
        WarActivity.SKILLS
    ]

    assert report.points_by_day == {1: Decimal("18881.550")}
    assert report.total == Decimal("18881.550")
    assert any(
        "За создание навыков: 75 × 225 = 16 875 очков" in calculation
        for calculation in details.calculations
    )


def test_parse_non_negative_int():
    assert parse_non_negative_int("0") == 0
    assert parse_non_negative_int("1 500") == 1500
    assert parse_non_negative_int("1_500") == 1500


def test_parse_non_negative_int_rejects_invalid_values():
    for value in ("", "-1", "1.5", "text"):
        try:
            parse_non_negative_int(value)
        except ValueError:
            continue
        raise AssertionError(f"{value!r} must be rejected")


def test_parse_thousand_based_resource_value():
    assert parse_editable_field_value("hammers", "1.5") == 1_500
    assert parse_editable_field_value("shells", "1,5") == 1_500
    assert parse_editable_field_value("hammers", "0.5") == 500
    assert parse_editable_field_value("shells", "0,125") == 125
    assert parse_editable_field_value("skills", "1.55") == 1_550
    assert parse_editable_field_value("mount_keys", "0.001") == 1
    assert parse_editable_field_value("mount_keys", "1") == 1_000
    assert parse_editable_field_value("pets", "1 500") == 1_500


def test_parse_thousand_based_resource_value_rejects_extra_precision():
    for value in ("", "-1", "1.5555", "1 500"):
        try:
            parse_editable_field_value("skills", value)
        except ValueError:
            continue
        raise AssertionError(f"{value!r} must be rejected")


def test_value_input_hints_show_actual_limits():
    assert _value_input_hint(EDITABLE_FIELDS["forge_level"]) == (
        "Введите целое число от 1 до 35."
    )
    assert _value_input_hint(EDITABLE_FIELDS["skill_summon_cost"]) == (
        "Введите целое число от 0 до 25 (%)."
    )
    assert _value_input_hint(EDITABLE_FIELDS["extra_mount_chance"]) == (
        "Введите целое число от 0 до 50 (%)."
    )
    hint = _value_input_hint(EDITABLE_FIELDS["hammers"])
    assert "запятую или точку" in hint
    assert "Например: 0.12 и 0,12 будут восприняты как 120" in hint


def test_input_parser_errors_are_in_russian():
    try:
        parse_non_negative_int("не число")
    except ValueError as error:
        assert str(error) == "Нужно ввести целое неотрицательное число"
    else:
        raise AssertionError("Invalid input must be rejected")

    try:
        parse_editable_field_value("hammers", "1.5555")
    except ValueError as error:
        assert "не более чем с тремя знаками" in str(error)
    else:
        raise AssertionError("Extra precision must be rejected")


def test_single_value_edit_stores_compact_state_and_shows_current_value(
    monkeypatch,
):
    class FakeBot:
        def __init__(self):
            self.data = {}
            self.edited = []

        def set_state(self, _user_id, _state):
            pass

        def add_data(self, _user_id, **data):
            self.data.update(data)

        def edit_message_text(
            self, text, chat_id, message_id, reply_markup=None
        ):
            self.edited.append((text, chat_id, message_id, reply_markup))

    monkeypatch.setattr(
        "tg.user_data.edit_value.get_active_user_or_prompt",
        lambda *_: UserData(
            account_id=7,
            user_id=42,
            username="tester",
            tag="Лидер",
            hammers=2_500,
        ),
    )
    bot = FakeBot()

    request_value(make_callback("user_data/edit/hammers"), bot)

    assert bot.data == {
        "value_edit_state": {"field_name": "hammers", "account_id": 7}
    }
    assert "Текущее значение: <b>2.50к</b>" in bot.edited[0][0]
    assert bot.edited[0][3].keyboard[0][0].callback_data == "resources"


def test_single_value_edit_saves_to_selected_account(monkeypatch):
    class FakeUserDataDB:
        def __init__(self):
            self.saved = []

        def set_value(
            self, user_id, username, field_name, value, *, account_id
        ):
            self.saved.append(
                (user_id, username, field_name, value, account_id)
            )

    class FakeBot:
        def __init__(self):
            self.data = {
                "value_edit_state": {
                    "field_name": "hammers",
                    "account_id": 7,
                }
            }

        def retrieve_data(self, _user_id):
            return nullcontext(self.data)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
        chat=SimpleNamespace(id=42),
        id=1,
        text="1.5",
    )
    database = FakeUserDataDB()
    opened = []
    updates = []
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    monkeypatch.setattr(
        "tg.user_data.edit_value.record_resource_update",
        lambda category, field: updates.append((category, field)),
    )
    monkeypatch.setattr(
        "tg.user_data.resources_menu",
        lambda message, bot, notice: opened.append(notice),
    )

    save_value(message, FakeBot())

    assert database.saved == [(42, "tester", "hammers", 1_500, 7)]
    assert updates == [("resources", "hammers")]
    assert opened == ["✅ Молотки: <b>1.50к</b> — сохранено."]


def test_fill_all_rejects_invalid_value_before_advancing_to_next_field(
    monkeypatch,
):
    current_user = UserData(
        account_id=7,
        user_id=42,
        username="tester",
        tag="Лидер",
        forge_level=10,
    )

    class FakeUserDataDB:
        def get_user(self, _user_id, _account_id):
            return current_user

    class FakeBot:
        def __init__(self):
            self.data = {
                "fill_state": {
                    "section": "technologies",
                    "field_names": [
                        field.name
                        for field in user_data_resources.TECHNOLOGY_FIELDS
                    ],
                    "index": 0,
                    "account_id": 7,
                    "account_tag": "Лидер",
                    "prompt_message_id": 1,
                },
            }
            self.edited = []

        def retrieve_data(self, _user_id):
            return nullcontext(self.data)

        def edit_message_text(
            self, text, chat_id, message_id, reply_markup=None
        ):
            self.edited.append((text, chat_id, message_id, reply_markup))

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
        chat=SimpleNamespace(id=42),
        id=1,
        text="36",
    )
    monkeypatch.setattr(
        "tg.user_data.get_user_data_db", lambda: FakeUserDataDB()
    )
    bot = FakeBot()

    save_fill_value(message, bot)

    assert bot.data["fill_state"]["index"] == 0
    assert "Значение не подходит" in bot.edited[0][0]
    assert "Текущее значение: <b>10</b>" in bot.edited[0][0]
    assert "от 1 до 35" in bot.edited[0][0]


def test_reminder_fill_starts_with_only_requested_fields(monkeypatch):
    class FakeBot:
        def __init__(self):
            self.data = {}
            self.edited = []

        def set_state(self, _user_id, _state):
            pass

        def add_data(self, _user_id, **data):
            self.data.update(data)

        def edit_message_text(
            self, text, chat_id, message_id, reply_markup=None
        ):
            self.edited.append((text, chat_id, message_id, reply_markup))

    bot = FakeBot()
    monkeypatch.setattr(
        "tg.user_data.fill.get_active_user_or_prompt",
        lambda *_: UserData(
            account_id=7,
            user_id=42,
            username="tester",
            tag="Лидер",
            hammers=2_500,
            extra_mount_chance=10,
        ),
    )

    fill_tracked_fields(
        make_callback("user_data/fill/tracked/3,10"),
        bot,
    )

    assert bot.data["fill_state"]["section"] == "reminder"
    assert bot.data["fill_state"]["field_names"] == (
        "hammers",
        "extra_mount_chance",
    )
    assert "Молотки" in bot.edited[0][0]
    assert "Текущее значение: <b>2.50к</b>" in bot.edited[0][0]
    assert [
        button.callback_data
        for row in bot.edited[0][3].keyboard
        for button in row
    ] == [
        "user_data/fill/skip",
        "home",
    ]
    assert len(bot.edited[0][3].keyboard[0]) == 2


def test_reminder_fill_saves_only_requested_fields(monkeypatch):
    class FakeUserDataDB:
        def __init__(self):
            self.saved = []
            self.user = UserData(
                account_id=7,
                user_id=42,
                username="tester",
                tag="Лидер",
                hammers=2_500,
                extra_mount_chance=5,
            )

        def get_user(self, _user_id, _account_id):
            return self.user

        def set_value(
            self, user_id, username, field_name, value, *, account_id
        ):
            self.user.set_value(field_name, value)
            self.saved.append(
                (user_id, username, field_name, value, account_id)
            )
            return self.user

    class FakeBot:
        def __init__(self):
            self.data = {
                "fill_state": {
                    "section": "reminder",
                    "field_names": ["hammers", "extra_mount_chance"],
                    "index": 0,
                    "account_id": 7,
                    "account_tag": "Лидер",
                    "prompt_message_id": 1,
                },
            }
            self.edited = []

        def retrieve_data(self, _user_id):
            return nullcontext(self.data)

        def add_data(self, _user_id, **data):
            self.data.update(data)

        def edit_message_text(
            self, text, chat_id, message_id, reply_markup=None
        ):
            self.edited.append((text, chat_id, message_id, reply_markup))

        def delete_state(self, _user_id):
            pass

    def message(text):
        return SimpleNamespace(
            from_user=SimpleNamespace(
                id=42,
                username="tester",
                first_name="Tester",
            ),
            chat=SimpleNamespace(id=42),
            id=1,
            text=text,
        )

    database = FakeUserDataDB()
    updates = []
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    monkeypatch.setattr(
        "tg.user_data.fill.record_resource_update",
        lambda category, field: updates.append((category, field)),
    )
    bot = FakeBot()

    save_fill_value(message("1.5"), bot)
    save_fill_value(message("10"), bot)

    assert database.saved == [
        (42, "tester", "hammers", 1500, 7),
        (42, "tester", "extra_mount_chance", 10, 7),
    ]
    assert updates == [
        ("resources", "hammers"),
        ("technologies", "extra_mount_chance"),
    ]
    assert "Текущее значение: <b>5</b>" in bot.edited[0][0]
    assert "Заполнение завершено" in bot.edited[-1][0]
    assert bot.edited[-1][3].keyboard[0][0].callback_data == "home"


def test_fill_all_can_skip_values_without_changing_them(monkeypatch):
    current_user = UserData(
        account_id=7,
        user_id=42,
        username="tester",
        tag="Лидер",
        hammers=2_500,
        extra_mount_chance=5,
    )

    class FakeUserDataDB:
        def get_user(self, _user_id, _account_id):
            return current_user

    class FakeBot:
        def __init__(self):
            self.data = {
                "fill_state": {
                    "section": "reminder",
                    "field_names": ["hammers", "extra_mount_chance"],
                    "index": 0,
                    "account_id": 7,
                    "account_tag": "Лидер",
                    "prompt_message_id": 1,
                },
            }
            self.edited = []
            self.deleted_states = []

        def retrieve_data(self, _user_id):
            return nullcontext(self.data)

        def add_data(self, _user_id, **data):
            self.data.update(data)

        def edit_message_text(
            self, text, chat_id, message_id, reply_markup=None
        ):
            self.edited.append((text, chat_id, message_id, reply_markup))

        def delete_state(self, user_id):
            self.deleted_states.append(user_id)

    monkeypatch.setattr(
        "tg.user_data.get_user_data_db", lambda: FakeUserDataDB()
    )
    bot = FakeBot()
    callback = make_callback("user_data/fill/skip")

    skip_fill_value(callback, bot)
    skip_fill_value(callback, bot)

    assert current_user.hammers.value == 2_500
    assert current_user.extra_mount_chance.value == 5
    assert "Текущее значение: <b>5</b>" in bot.edited[0][0]
    assert "Заполнение завершено" in bot.edited[-1][0]
    assert bot.deleted_states == [42]


def test_format_points_rounds_and_adds_suffixes():
    assert format_points(Decimal("999.995")) == "1.00к"
    assert format_points(Decimal("1234.567")) == "1.23к"
    assert format_points(Decimal("1234567.89")) == "1.23м"
