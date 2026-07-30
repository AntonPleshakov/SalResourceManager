from pathlib import Path

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.user_data import UserDataDB
from resources.user_data import EDITABLE_FIELDS, UserData, parse_non_negative_int


class FakeWorksheetManager:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.update_calls = 0

    def fetch(self):
        pass

    def get_all_values(self):
        return self.rows

    def add_row(self, row):
        self.rows.append(row)

    def update_values(self, rows):
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
