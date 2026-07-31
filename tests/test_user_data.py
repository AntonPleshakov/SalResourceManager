import importlib
import sys
from pathlib import Path

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.user_data import UserDataDB
from db.war_stages import WarStagesDB
from resources.user_data import EDITABLE_FIELDS, UserData, parse_non_negative_int
from resources.war import DEFAULT_WAR_STAGES, WarActivity, WarPointsCalculator


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
        mount_keys=1,
        skills=2,
        shells=3,
        hammers=4,
        gems=5,
        pets=6,
        unmerged_mounts=7,
        skill_summon_cost=8,
        extra_egg_chance=9,
        mount_summon_cost=10,
        extra_mount_chance=11,
    )

    restored = UserData.from_row(original.to_row())

    assert restored == original
    assert set(EDITABLE_FIELDS) == {
        "mount_keys",
        "skills",
        "shells",
        "hammers",
        "gems",
        "pets",
        "unmerged_mounts",
        "skill_summon_cost",
        "extra_egg_chance",
        "mount_summon_cost",
        "extra_mount_chance",
    }


def test_database_creates_and_updates_user():
    manager = FakeWorksheetManager()
    database = UserDataDB(manager)

    created = database.get_or_create(42, "tester")
    updated = database.set_value(42, "tester", "gems", 1500)

    assert created is updated
    assert updated.gems.value == 1500
    assert len(manager.rows) == 1
    assert UserData.from_row(manager.rows[0]).gems.value == 1500


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
        {"gems": 1500, "pets": 3, "extra_mount_chance": 10},
    )

    assert manager.update_calls == 1
    assert updated.gems.value == 1500
    assert updated.pets.value == 3
    assert updated.extra_mount_chance.value == 10


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

    database.set_values(42, "tester", {"gems": 1500})

    assert UserData.from_row(replacement_manager.rows[0]).gems.value == 1500


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


def test_war_points_calculator_is_ready_for_future_scoring_rules():
    user = UserData(user_id=42, username="tester", gems=100)
    calculator = WarPointsCalculator({WarActivity.FORGING: lambda _: 25})

    report = calculator.calculate([user], DEFAULT_WAR_STAGES)

    assert report.points_by_day == {1: 25, 2: 0, 3: 25, 4: 0, 5: 25}
    assert report.total == 75


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
