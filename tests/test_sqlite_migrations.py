import sqlite3

import pytest

from db.sqlite.migration_runner import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    load_migrations,
)


def write_migration(directory, filename, sql):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(sql, encoding="utf-8")


def test_initial_migrations_have_one_global_continuous_history():
    migrations = load_migrations()

    assert [migration.label for migration in migrations] == [
        "0001_create_admins",
        "0002_create_access_group",
        "0003_create_release_views",
        "0004_create_user_data",
        "0005_create_war_stages",
        "0006_drop_war_stages",
    ]
    assert all(
        "IF NOT EXISTS" not in migration.path.read_text(encoding="utf-8").upper()
        for migration in migrations
    )


def test_runner_applies_only_pending_migrations(tmp_path):
    partial_directory = tmp_path / "partial"
    migrations = load_migrations()
    for migration in migrations[:2]:
        write_migration(
            partial_directory,
            migration.path.name,
            migration.path.read_text(encoding="utf-8"),
        )

    with sqlite3.connect(tmp_path / "database.db") as connection:
        first_applied = apply_migrations(connection, partial_directory)
        second_applied = apply_migrations(connection, MIGRATIONS_DIR)
        final_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert [migration.version for migration in first_applied] == [1, 2]
    assert [migration.version for migration in second_applied] == [3, 4, 5, 6]
    assert final_version == 6


def test_war_stages_table_is_removed_from_final_schema(tmp_path):
    with sqlite3.connect(tmp_path / "database.db") as connection:
        apply_migrations(connection)
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'war_stages'"
        ).fetchone()

    assert table is None


def test_failed_migration_rolls_back_its_schema_changes(tmp_path):
    migrations = tmp_path / "migrations"
    write_migration(
        migrations,
        "0001_create_items.sql",
        "CREATE TABLE items (id INTEGER PRIMARY KEY);\n",
    )
    write_migration(
        migrations,
        "0002_break_items.sql",
        "ALTER TABLE items ADD COLUMN note TEXT; "
        "INSERT INTO missing_table VALUES (1);\n",
    )

    with sqlite3.connect(tmp_path / "database.db") as connection:
        with pytest.raises(MigrationError, match="0002_break_items"):
            apply_migrations(connection, migrations)

        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = connection.execute("PRAGMA table_info(items)").fetchall()

    assert version == 1
    assert [column[1] for column in columns] == ["id"]


def test_runner_rejects_a_gap_in_migration_versions(tmp_path):
    migrations = tmp_path / "migrations"
    write_migration(migrations, "0001_first.sql", "SELECT 1;\n")
    write_migration(migrations, "0003_third.sql", "SELECT 3;\n")

    with pytest.raises(MigrationError, match="must be continuous"):
        load_migrations(migrations)


def test_runner_rejects_a_database_from_a_newer_application(tmp_path):
    with sqlite3.connect(tmp_path / "database.db") as connection:
        connection.execute("PRAGMA user_version = 7")

        with pytest.raises(MigrationError, match="newer than supported"):
            apply_migrations(connection)
