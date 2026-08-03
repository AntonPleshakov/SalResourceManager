import importlib
import sys
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.user_data import UserDataDB
from db.war_stages import WarStagesDB
from resources.user_data import (
    EDITABLE_FIELDS,
    UserData,
    parse_editable_field_value,
    parse_non_negative_int,
)
from resources.war import (
    DEFAULT_WAR_STAGES,
    WarActivity,
    WarPointsCalculator,
)
from resources.war_rules.forging import (
    FORGE_WEAPON_CHANCES,
    forge_weapon_chances,
    weapon_points,
)
from tg.utils import format_points
from tg.user_data import _get_group_tag, save_all_values


class FakeWorksheetManager:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.update_calls = 0
        self.fetch_error = None
        self.update_error = None
        self.add_error = None

    def fetch(self):
        if self.fetch_error:
            raise self.fetch_error

    def get_all_values(self):
        return self.rows

    def add_row(self, row):
        if self.add_error:
            raise self.add_error
        self.rows.append(row)

    def update_values(self, rows):
        if self.update_error:
            raise self.update_error
        self.update_calls += 1
        self.rows = rows


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
    assert header[header.index("Пользователь") + 1] == "Тег"
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


def test_database_creates_and_updates_user():
    manager = FakeWorksheetManager()
    database = UserDataDB(manager)

    created = database.get_or_create(42, "tester")
    updated = database.set_value(
        42, "tester", "pets", 1500, updated_on=date(2026, 8, 2)
    )

    assert created is updated
    assert updated.pets.value == 1500
    assert updated.get_updated_on("pets") == date(2026, 8, 2)
    assert len(manager.rows) == 1
    assert UserData.from_row(manager.rows[0]).pets.value == 1500


def test_database_loads_existing_users():
    existing = UserData(user_id=42, username="tester", pets=12)
    database = UserDataDB(FakeWorksheetManager([existing.to_row()]))

    loaded = database.get_user(42)

    assert loaded is not None
    assert loaded.pets.value == 12


def test_database_returns_resource_table_url():
    database = UserDataDB(
        FakeWorksheetManager(), "https://docs.google.com/spreadsheets/d/example"
    )

    assert database.get_url() == "https://docs.google.com/spreadsheets/d/example"


def test_database_saves_multiple_fields_in_one_update():
    existing = UserData(user_id=42, username="tester")
    manager = FakeWorksheetManager([existing.to_row()])
    database = UserDataDB(manager)

    updated = database.set_values(
        42,
        "tester",
        {"hammers": 1500, "pets": 3, "extra_mount_chance": 10},
        updated_on=date(2026, 8, 2),
    )

    assert manager.update_calls == 1
    assert updated.hammers.value == 1500
    assert updated.pets.value == 3
    assert updated.extra_mount_chance.value == 10
    assert updated.get_updated_on("hammers") == date(2026, 8, 2)
    assert updated.get_updated_on("pets") == date(2026, 8, 2)
    assert updated.get_updated_on("extra_mount_chance") == date(2026, 8, 2)


def test_user_rows_preserve_blank_update_dates():
    user = UserData(user_id=42, username="tester", pets=100)
    restored = UserData.from_row(user.to_row())

    assert restored.pets.value == 100
    assert restored.get_updated_on("pets") is None


def test_updating_technology_marks_its_own_update_date():
    database = UserDataDB(FakeWorksheetManager())

    user = database.set_value(
        42,
        "tester",
        "forge_level",
        10,
        updated_on=date(2026, 8, 2),
    )

    assert user.get_updated_on("forge_level") == date(2026, 8, 2)
    assert user.get_updated_on("mount_keys") is None


def test_database_rejects_unknown_forge_level():
    database = UserDataDB(FakeWorksheetManager())

    try:
        database.set_value(42, "tester", "forge_level", 36)
    except ValueError as error:
        assert str(error) == "Forge level must be between 1 and 35"
    else:
        raise AssertionError("Forge level above 35 must be rejected")


def test_database_rejects_excessive_skill_summon_cost_reduction():
    database = UserDataDB(FakeWorksheetManager())

    try:
        database.set_value(42, "tester", "skill_summon_cost", 26)
    except ValueError as error:
        assert str(error) == "Skill summon cost reduction must be between 0 and 25"
    else:
        raise AssertionError("Skill summon cost reduction above 25 must be rejected")


def test_database_rejects_excessive_mount_summon_cost_reduction():
    database = UserDataDB(FakeWorksheetManager())

    try:
        database.set_value(42, "tester", "mount_summon_cost", 26)
    except ValueError as error:
        assert str(error) == "Mount summon cost reduction must be between 0 and 25"
    else:
        raise AssertionError("Mount summon cost reduction above 25 must be rejected")


def test_database_rejects_excessive_extra_mount_chance():
    database = UserDataDB(FakeWorksheetManager())

    try:
        database.set_value(42, "tester", "extra_mount_chance", 51)
    except ValueError as error:
        assert str(error) == "Extra mount chance must be between 0 and 50"
    else:
        raise AssertionError("Extra mount chance above 50 must be rejected")


def test_user_data_reconnects_after_failed_read(monkeypatch):
    broken_manager = FakeWorksheetManager()
    broken_database = UserDataDB(broken_manager)
    broken_manager.fetch_error = ConnectionError()
    replacement_manager = FakeWorksheetManager([UserData(user_id=42).to_row()])
    monkeypatch.setattr(
        broken_database,
        "_reconnect",
        lambda: setattr(broken_database, "_manager", replacement_manager),
    )

    broken_database.fetch()

    assert broken_database.get_user(42) is not None


def test_new_user_batch_save_reconnects_before_retrying_add(monkeypatch):
    broken_manager = FakeWorksheetManager()
    database = UserDataDB(broken_manager)
    broken_manager.add_error = ConnectionError()
    replacement_manager = FakeWorksheetManager()
    monkeypatch.setattr(
        database,
        "_reconnect",
        lambda: setattr(database, "_manager", replacement_manager),
    )

    database.set_values(42, "tester", {"pets": 1500})

    assert UserData.from_row(replacement_manager.rows[0]).pets.value == 1500


def test_war_stages_reconnect_after_failed_write(monkeypatch):
    broken_manager = FakeWorksheetManager()
    broken_database = WarStagesDB(broken_manager)
    broken_manager.update_error = ConnectionError()
    replacement_manager = FakeWorksheetManager()
    monkeypatch.setattr(
        broken_database,
        "_reconnect",
        lambda: setattr(broken_database, "_manager", replacement_manager),
    )

    broken_database.set_activity(1, 0, WarActivity.PETS)

    assert replacement_manager.rows[0] == ["1", "Питомцы", "Подземелья", "Навыки"]


def test_admins_db_reconnects_before_retrying_add(monkeypatch):
    class FakeSpreadsheet:
        def get_worksheet(self, _):
            return FakeWorksheetManager()

    class FakeGSheetsManager:
        def open(self, _):
            return FakeSpreadsheet()

    import db.gapi.gsheets_manager as gsheets_manager_module

    monkeypatch.setattr(
        gsheets_manager_module, "GSheetsManager", FakeGSheetsManager
    )
    monkeypatch.delitem(sys.modules, "db.admins", raising=False)
    admins_module = importlib.import_module("db.admins")

    assert admins_module.admins_db is None

    broken_manager = FakeWorksheetManager()
    database = admins_module.AdminsDB(broken_manager)
    broken_manager.add_error = ConnectionError()
    replacement_manager = FakeWorksheetManager()
    monkeypatch.setattr(
        database,
        "_reconnect",
        lambda: setattr(database, "_manager", replacement_manager),
    )

    database.add_admin(admins_module.Admin("alice", 42))

    assert database.get_admin(42).username.value == "alice"
    assert replacement_manager.rows == [["alice", "42"]]


def test_war_stages_are_initialized_and_can_be_changed():
    manager = FakeWorksheetManager()
    database = WarStagesDB(manager)

    assert database.get_stages() == DEFAULT_WAR_STAGES
    database.set_activity(1, 0, WarActivity.PETS)

    assert database.get_stages()[1][0] == WarActivity.PETS
    assert manager.rows[0] == ["1", "Питомцы", "Подземелья", "Навыки"]


def test_war_stages_fetch_does_not_write():
    manager = FakeWorksheetManager()
    database = WarStagesDB(manager)

    database.fetch()

    assert manager.update_calls == 0


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
    assert report.points_by_day == {1: 33_612}
    assert report.total == 33_612


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


def test_war_points_calculator_estimates_skill_points():
    user = UserData(user_id=42, skills=2490, skill_summon_cost=17)

    report = WarPointsCalculator().calculate(
        [user], {1: (WarActivity.SKILLS,)}
    )

    assert report.points_by_day == {1: Decimal("562256.550")}
    assert report.total == Decimal("562256.550")


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
    assert parse_editable_field_value("mount_keys", "1") == 1_000
    assert parse_editable_field_value("pets", "1 500") == 1_500


def test_parse_thousand_based_resource_value_rejects_extra_precision():
    for value in ("", "-1", "1.55", "1 500"):
        try:
            parse_editable_field_value("skills", value)
        except ValueError:
            continue
        raise AssertionError(f"{value!r} must be rejected")


def test_fill_all_rejects_invalid_value_before_advancing_to_next_field():
    class FakeBot:
        def __init__(self):
            self.data = {
                "fill_section": "technologies",
                "fill_index": 0,
                "fill_values": {},
            }
            self.replies = []

        def retrieve_data(self, _user_id):
            return nullcontext(self.data)

        def reply_to(self, _message, text):
            self.replies.append(text)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
        chat=SimpleNamespace(id=42),
        id=1,
        text="36",
    )
    bot = FakeBot()

    save_all_values(message, bot)

    assert bot.data["fill_index"] == 0
    assert bot.data["fill_values"] == {}
    assert "Уровень кузницы" in bot.replies[0]
    assert "between 1 and 35" in bot.replies[0]


def test_format_points_rounds_and_adds_suffixes():
    assert format_points(Decimal("999.995")) == "1.00к"
    assert format_points(Decimal("1234.567")) == "1.23к"
    assert format_points(Decimal("1234567.89")) == "1.23м"
