import sqlite3
from datetime import date

import pytest

from db.access_group import (
    ACCESS_GROUP_ID_KEY,
    AccessGroupDB,
    get_access_group_db,
    set_access_group_db,
)
from db.admins import Admin, AdminsDB, get_admins_db, set_admins_db
from db.release_views import (
    RELEASE_VIEWS_HEADER,
    ReleaseViewsDB,
    get_release_views_db,
    set_release_views_db,
)
from db.sqlite.access_group import AccessGroupDB as SQLiteAccessGroupDB
from db.sqlite.admins import AdminsDB as SQLiteAdminsDB
from db.sqlite.database import SQLiteDatabase
from db.sqlite.initializer import initialize_sqlite_databases
from db.sqlite.release_views import ReleaseViewsDB as SQLiteReleaseViewsDB
from db.sqlite.user_data import UserDataDB as SQLiteUserDataDB
from db.sqlite.war_stages import WarStagesDB as SQLiteWarStagesDB
from db.user_data import UserDataDB, get_user_data_db, set_user_data_db
from db.war_stages import (
    WarStagesDB,
    get_war_stages_db,
    set_war_stages_db,
)
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


def make_google_databases():
    user = UserData(
        user_id=42,
        username="player",
        tag="TAG",
        mount_keys=1200,
        pets=7,
    )
    user.mark_updated("mount_keys", date(2026, 8, 7))
    return (
        AdminsDB(FakeWorksheetManager([["admin", "1"]])),
        AccessGroupDB(
            FakeWorksheetManager([[ACCESS_GROUP_ID_KEY, "-100123"]])
        ),
        ReleaseViewsDB(
            FakeWorksheetManager(
                [["42", "player", "1.2.3"]],
                header=RELEASE_VIEWS_HEADER,
            )
        ),
        UserDataDB(FakeWorksheetManager([user.to_row()]), "google-url"),
        WarStagesDB(
            FakeWorksheetManager(
                WarStagesDB._stages_to_rows(DEFAULT_WAR_STAGES)
            )
        ),
    )


def populate_sqlite(database_path, google_databases):
    admins, access_group, release_views, user_data, war_stages = (
        google_databases
    )
    database = SQLiteDatabase(database_path)
    SQLiteAdminsDB(database, admins).replace_all(admins.get_admins())
    SQLiteAccessGroupDB(database, access_group).replace(
        access_group.get_group_id()
    )
    SQLiteReleaseViewsDB(database, release_views).replace_all(
        release_views.get_users()
    )
    SQLiteUserDataDB(database, user_data).replace_all(user_data.get_users())
    SQLiteWarStagesDB(database, war_stages).replace_all(
        war_stages.get_stages()
    )
    database.close()


def restore_google_singletons(google_databases):
    admins, access_group, release_views, user_data, war_stages = (
        google_databases
    )
    set_admins_db(admins)
    set_access_group_db(access_group)
    set_release_views_db(release_views)
    set_user_data_db(user_data)
    set_war_stages_db(war_stages)


def test_initializer_activates_sqlite_reads(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)

    databases = initialize_sqlite_databases(
        *google,
        database_path=database_path,
    )
    try:
        assert get_admins_db() is databases.admins
        assert get_access_group_db() is databases.access_group
        assert get_release_views_db() is databases.release_views
        assert get_user_data_db() is databases.user_data
        assert get_war_stages_db() is databases.war_stages

        google[0]._admins = [Admin("changed-only-in-google-memory", 99)]
        google[1]._group_id = -999
        google[2]._users = {99: ("changed", "9.9.9")}
        google[3]._users = {99: UserData(user_id=99, username="changed")}
        google[4]._stages = {
            1: (WarActivity.PETS, WarActivity.PETS, WarActivity.PETS)
        }

        assert [
            admin.user_id.value for admin in databases.admins.get_admins()
        ] == [1]
        assert databases.admins.is_admin(1)
        assert databases.access_group.get_group_id() == -100123
        assert databases.release_views.get_last_seen_version(42) == "1.2.3"
        assert databases.user_data.get_user(42).username.value == "player"
        assert databases.user_data.get_url() == "google-url"
        assert databases.war_stages.get_stages() == DEFAULT_WAR_STAGES
    finally:
        databases.database.close()
        restore_google_singletons(google)


def test_initializer_does_not_compare_google_and_sqlite(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)
    google[0]._admins.append(Admin("google-only", 2))

    databases = initialize_sqlite_databases(
        *google,
        database_path=database_path,
    )
    try:
        assert [
            admin.user_id.value for admin in databases.admins.get_admins()
        ] == [1]
    finally:
        databases.database.close()
        restore_google_singletons(google)


def test_databases_write_google_first_then_sqlite(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)
    databases = initialize_sqlite_databases(
        *google,
        database_path=database_path,
    )
    try:
        databases.admins.add_admin(Admin("second", 2))
        databases.access_group.set_group_id(-200)
        databases.release_views.mark_seen(7, "viewer", "2.0.0")
        user = databases.user_data.set_values(
            42,
            "renamed",
            {"pets": 9},
            updated_on=date(2026, 8, 8),
        )
        databases.war_stages.set_activity(1, 0, WarActivity.PETS)

        assert [admin.user_id.value for admin in google[0].get_admins()] == [
            1,
            2,
        ]
        assert [
            admin.user_id.value for admin in databases.admins.get_admins()
        ] == [1, 2]
        assert google[1].get_group_id() == -200
        assert databases.access_group.get_group_id() == -200
        assert google[2].get_last_seen_version(7) == "2.0.0"
        assert databases.release_views.get_last_seen_version(7) == "2.0.0"
        assert google[3].get_user(42).pets.value == 9
        assert user.pets.value == 9
        assert google[4].get_stages()[1][0] == WarActivity.PETS
        assert databases.war_stages.get_stages()[1][0] == WarActivity.PETS
    finally:
        databases.database.close()
        restore_google_singletons(google)


def test_failed_google_write_does_not_update_sqlite(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)
    databases = initialize_sqlite_databases(
        *google,
        database_path=database_path,
    )
    google[1]._manager.update_error = ValueError("Google write failed")
    try:
        with pytest.raises(ValueError, match="Google write failed"):
            databases.access_group.set_group_id(-200)

        assert databases.access_group.get_group_id() == -100123
    finally:
        databases.database.close()
        restore_google_singletons(google)


def test_table_replacement_is_transactional(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)
    database = SQLiteDatabase(database_path)
    admins = SQLiteAdminsDB(database, google[0])
    duplicate_admins = [
        Admin("first", 7),
        Admin("duplicate", 7),
    ]

    with pytest.raises(sqlite3.IntegrityError):
        admins.replace_all(duplicate_admins)

    assert [admin.user_id.value for admin in admins.get_admins()] == [1]
    database.close()


def test_initializer_does_not_validate_existing_schema(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    google = make_google_databases()
    populate_sqlite(database_path, google)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE admins")
        connection.execute("CREATE TABLE admins (wrong_column TEXT)")

    databases = initialize_sqlite_databases(
        *google,
        database_path=database_path,
    )
    databases.database.close()
    restore_google_singletons(google)
