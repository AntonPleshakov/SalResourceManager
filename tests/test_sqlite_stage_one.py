import sqlite3
from datetime import date

import pytest

from db.access_group import AccessGroupDB
from db.admins import Admin, AdminsDB
from db.release_views import RELEASE_VIEWS_HEADER, ReleaseViewsDB
from db.sqlite.mirror import SQLiteSchemaError
from db.sqlite.stage_one import initialize_sqlite_stage_one
from db.user_data import UserDataDB
from db.war_stages import WarStagesDB
from resources.user_data import UserData
from resources.war import DEFAULT_WAR_STAGES, WarActivity


class FakeWorksheetManager:
    def __init__(self, rows=None, header=None):
        self.rows = [list(row) for row in (rows or [])]
        self.header = header or []
        self.update_error = None

    def get_all_values(self):
        return [list(row) for row in self.rows]

    def get_header(self):
        return self.header

    def set_header(self, header):
        self.header = header

    def ensure_header(self, header):
        self.header = header

    def fetch(self):
        pass

    def add_row(self, row):
        self.rows.append(list(row))

    def update_values(self, rows):
        if self.update_error:
            raise self.update_error
        self.rows = [list(row) for row in rows]


class MirrorSource:
    def enable_sqlite_mirror(self, writer):
        self.sqlite_writer = writer


class AdminsSource(MirrorSource):
    def __init__(self, admins):
        self.admins = admins

    def get_admins(self):
        return self.admins


class AccessGroupSource(MirrorSource):
    def __init__(self, group_id):
        self.group_id = group_id

    def get_group_id(self):
        return self.group_id


class ReleaseViewsSource(MirrorSource):
    def __init__(self, users):
        self.users = users

    def get_users(self):
        return dict(self.users)


class UserDataSource(MirrorSource):
    def __init__(self, users):
        self.users = users

    def get_users(self):
        return self.users


class WarStagesSource(MirrorSource):
    def __init__(self, stages):
        self.stages = stages

    def get_stages(self):
        return dict(self.stages)


def read_rows(database_path, table, columns):
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            f"SELECT {columns} FROM {table} ORDER BY 1"
        ).fetchall()


def make_sources():
    user = UserData(
        user_id=42,
        username="player",
        tag="TAG",
        mount_keys=1200,
        pets=7,
    )
    user.mark_updated("mount_keys", date(2026, 8, 7))
    return (
        AdminsSource([Admin("admin", 1)]),
        AccessGroupSource(-100123),
        ReleaseViewsSource({42: ("player", "1.2.3")}),
        UserDataSource([user]),
        WarStagesSource(DEFAULT_WAR_STAGES),
    )


def test_stage_one_imports_verifies_and_enables_dual_write(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    sources = make_sources()

    mirror = initialize_sqlite_stage_one(
        *sources,
        database_path=database_path,
    )

    assert read_rows(database_path, "admins", "user_id, username") == [
        (1, "admin")
    ]
    assert read_rows(database_path, "access_group", "singleton, group_id") == [
        (1, -100123)
    ]
    assert read_rows(
        database_path,
        "release_views",
        "user_id, username, last_seen_version",
    ) == [(42, "player", "1.2.3")]
    assert read_rows(
        database_path,
        "user_data",
        "user_id, username, tag, mount_keys, mount_keys_updated_on, pets",
    ) == [(42, "player", "TAG", 1200, "2026-08-07", 7)]
    assert len(read_rows(database_path, "war_stages", "*")) == 5

    admins, access_group, release_views, user_data, war_stages = sources
    admins.admins.append(Admin("second", 2))
    admins.sqlite_writer()
    access_group.group_id = None
    access_group.sqlite_writer()
    release_views.users[42] = ("renamed", "2.0.0")
    release_views.sqlite_writer()
    user_data.users[0].pets.value = 9
    user_data.sqlite_writer()
    war_stages.stages = {
        1: (
            WarActivity.PETS,
            WarActivity.SKILLS,
            WarActivity.FORGING,
        )
    }
    war_stages.sqlite_writer()

    assert read_rows(database_path, "admins", "user_id, username") == [
        (1, "admin"),
        (2, "second"),
    ]
    assert read_rows(database_path, "access_group", "*") == []
    assert read_rows(
        database_path,
        "release_views",
        "user_id, username, last_seen_version",
    ) == [(42, "renamed", "2.0.0")]
    assert read_rows(database_path, "user_data", "user_id, pets") == [(42, 9)]
    assert read_rows(database_path, "war_stages", "*") == [
        (1, "pets", "skills", "forging")
    ]
    mirror.close()


def test_stage_one_replaces_previous_sqlite_snapshot_on_restart(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    sources = make_sources()
    first_mirror = initialize_sqlite_stage_one(
        *sources,
        database_path=database_path,
    )
    first_mirror.close()

    sources[0].admins = [Admin("replacement", 99)]
    second_mirror = initialize_sqlite_stage_one(
        *sources,
        database_path=database_path,
    )

    assert read_rows(database_path, "admins", "user_id, username") == [
        (99, "replacement")
    ]
    second_mirror.close()


def test_import_rolls_back_all_tables_when_a_later_table_fails(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    sources = make_sources()
    mirror = initialize_sqlite_stage_one(
        *sources,
        database_path=database_path,
    )
    duplicate_users = [
        UserData(user_id=7, username="first"),
        UserData(user_id=7, username="duplicate"),
    ]

    with pytest.raises(sqlite3.IntegrityError):
        mirror.import_from_google(
            admins=[Admin("replacement", 99)],
            access_group_id=-999,
            release_views={},
            users=duplicate_users,
            war_stages={},
        )

    assert read_rows(database_path, "admins", "user_id, username") == [
        (1, "admin")
    ]
    assert read_rows(database_path, "access_group", "singleton, group_id") == [
        (1, -100123)
    ]
    mirror.close()


def test_stage_one_rejects_an_unexpected_schema(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    mirror = initialize_sqlite_stage_one(
        *make_sources(),
        database_path=database_path,
    )
    mirror.close()
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE admins")
        connection.execute("CREATE TABLE admins (wrong_column TEXT)")

    with pytest.raises(SQLiteSchemaError, match="Unexpected columns for admins"):
        initialize_sqlite_stage_one(
            *make_sources(),
            database_path=database_path,
        )


def test_successful_google_writes_call_the_sqlite_mirror():
    callbacks = []

    admins = AdminsDB(FakeWorksheetManager())
    admins.enable_sqlite_mirror(lambda: callbacks.append("admins"))
    admins.add_admin(Admin("admin", 1))

    access_group = AccessGroupDB(FakeWorksheetManager())
    access_group.enable_sqlite_mirror(lambda: callbacks.append("access_group"))
    access_group.set_group_id(-100123)

    release_views = ReleaseViewsDB(
        FakeWorksheetManager(header=RELEASE_VIEWS_HEADER)
    )
    release_views.enable_sqlite_mirror(lambda: callbacks.append("release_views"))
    release_views.mark_seen(42, "player", "1.0.0")

    user_data = UserDataDB(FakeWorksheetManager())
    user_data.enable_sqlite_mirror(lambda: callbacks.append("user_data"))
    user_data.set_values(42, "player", {"pets": 10})

    war_stages = WarStagesDB(
        FakeWorksheetManager(WarStagesDB._stages_to_rows(DEFAULT_WAR_STAGES))
    )
    war_stages.enable_sqlite_mirror(lambda: callbacks.append("war_stages"))
    war_stages.set_activity(1, 0, WarActivity.PETS)

    assert callbacks == [
        "admins",
        "access_group",
        "release_views",
        "user_data",
        "war_stages",
    ]


def test_failed_google_write_does_not_call_the_sqlite_mirror():
    manager = FakeWorksheetManager()
    manager.update_error = ValueError("Google write failed")
    database = AccessGroupDB(manager)
    callbacks = []
    database.enable_sqlite_mirror(lambda: callbacks.append("sqlite"))

    with pytest.raises(ValueError, match="Google write failed"):
        database.set_group_id(-100123)

    assert callbacks == []
