import sqlite3
from datetime import date

from db.access_group import get_access_group_db
from db.admins import Admin, get_admins_db
from db.release_views import get_release_views_db
from db.sqlite.initializer import initialize_sqlite_databases
from db.user_data import get_user_data_db


def test_initializer_applies_migrations_and_activates_databases(tmp_path):
    databases = initialize_sqlite_databases(
        database_path=tmp_path / "sal_resources.db"
    )
    try:
        assert get_admins_db() is databases.admins
        assert get_access_group_db() is databases.access_group
        assert get_release_views_db() is databases.release_views
        assert get_user_data_db() is databases.user_data
        assert databases.admins.get_admins() == []
        assert databases.access_group.get_group_id() is None
        assert databases.release_views.get_users_count() == 0
        assert databases.user_data.get_users() == []
    finally:
        databases.database.close()


def test_sqlite_databases_write_directly_and_persist(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    databases = initialize_sqlite_databases(database_path=database_path)
    databases.admins.add_admin(Admin("first", 1))
    databases.admins.add_admin(Admin("second", 2))
    databases.admins.del_admin(1)
    databases.access_group.set_group_id(-100123)
    databases.release_views.mark_seen(42, "player", "1.2.3")
    databases.release_views.update_username(42, "renamed")
    databases.user_data.set_values(
        42,
        "player",
        {"pets": 9, "hammers": 1200},
        updated_on=date(2026, 8, 8),
        tag="TAG",
    )
    databases.database.close()

    restored = initialize_sqlite_databases(database_path=database_path)
    try:
        assert [admin.user_id.value for admin in restored.admins.get_admins()] == [2]
        assert restored.access_group.get_group_id() == -100123
        assert restored.release_views.get_users() == {
            42: ("renamed", "1.2.3")
        }
        user = restored.user_data.get_user(42)
        assert user.username.value == "player"
        assert user.tag.value == "TAG"
        assert user.pets.value == 9
        assert user.hammers.value == 1200
        assert user.get_updated_on("pets") == date(2026, 8, 8)
    finally:
        restored.database.close()


def test_initializer_does_not_validate_existing_schema(tmp_path):
    database_path = tmp_path / "sal_resources.db"
    databases = initialize_sqlite_databases(database_path=database_path)
    databases.database.close()
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE admins")
        connection.execute("CREATE TABLE admins (wrong_column TEXT)")

    restored = initialize_sqlite_databases(database_path=database_path)
    restored.database.close()
