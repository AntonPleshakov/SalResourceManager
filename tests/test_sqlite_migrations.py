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


LEGACY_IDENTITY_COLUMNS = ("user_id", "username", "tag")
MIGRATED_DATA_COLUMNS = (
    "mount_keys",
    "mount_keys_updated_on",
    "skills",
    "skills_updated_on",
    "shells",
    "shells_updated_on",
    "hammers",
    "hammers_updated_on",
    "pets",
    "pets_updated_on",
    "unmerged_mounts",
    "unmerged_mounts_updated_on",
    "forge_level",
    "forge_level_updated_on",
    "skill_summon_cost",
    "skill_summon_cost_updated_on",
    "extra_egg_chance",
    "extra_egg_chance_updated_on",
    "mount_summon_cost",
    "mount_summon_cost_updated_on",
    "extra_mount_chance",
    "extra_mount_chance_updated_on",
    "eggs_per_hatch_batch",
    "max_egg_level",
    "hatch_batches_common",
    "hatch_batches_rare",
    "hatch_batches_epic",
    "hatch_batches_legendary",
    "hatch_batches_ultimate",
    "hatch_batches_mythic",
)


def copy_initial_migrations(directory, count):
    for migration in load_migrations()[:count]:
        write_migration(
            directory,
            migration.path.name,
            migration.path.read_text(encoding="utf-8"),
        )


def legacy_user_row(user_id, username, tag, value_base):
    row = {"user_id": user_id, "username": username, "tag": tag}
    for index, column in enumerate(MIGRATED_DATA_COLUMNS, start=1):
        row[column] = (
            f"date-marker-{value_base}-{index}"
            if column.endswith("_updated_on")
            else value_base + index
        )
    return row


def insert_legacy_user(connection, row):
    columns = (*LEGACY_IDENTITY_COLUMNS, *MIGRATED_DATA_COLUMNS)
    connection.execute(
        f"INSERT INTO user_data ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        tuple(row[column] for column in columns),
    )


def prepare_version_7_database(database_path, migrations, rows):
    copy_initial_migrations(migrations, 7)
    with sqlite3.connect(database_path) as connection:
        apply_migrations(connection, migrations)
        for row in rows:
            insert_legacy_user(connection, row)


def test_initial_migrations_have_one_global_continuous_history():
    migrations = load_migrations()

    assert [migration.label for migration in migrations] == [
        "0001_create_admins",
        "0002_create_access_group",
        "0003_create_release_views",
        "0004_create_user_data",
        "0005_create_war_stages",
        "0006_drop_war_stages",
        "0007_add_pet_settings",
        "0008_add_game_accounts",
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
    assert [migration.version for migration in second_applied] == [3, 4, 5, 6, 7, 8]
    assert final_version == 8


def test_war_stages_table_is_removed_from_final_schema(tmp_path):
    with sqlite3.connect(tmp_path / "database.db") as connection:
        apply_migrations(connection)
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'war_stages'"
        ).fetchone()

    assert table is None


def test_game_account_migration_preserves_every_value_for_every_user(tmp_path):
    database_path = tmp_path / "database.db"
    version_7_migrations = tmp_path / "version_7"
    legacy_rows = [
        legacy_user_row(42, "telegram_one", "Hero α", 1_000),
        legacy_user_row(77, "telegram_two", "Герой β", 2_000),
    ]
    prepare_version_7_database(
        database_path,
        version_7_migrations,
        legacy_rows,
    )

    with sqlite3.connect(database_path) as connection:
        applied = apply_migrations(connection, MIGRATIONS_DIR)
        migrated_rows = connection.execute(
            "SELECT ga.user_id, tu.username, ga.tag, "
            + ", ".join(f'ud."{column}"' for column in MIGRATED_DATA_COLUMNS)
            + " FROM user_data ud "
            "JOIN game_accounts ga ON ga.account_id = ud.account_id "
            "JOIN telegram_users tu ON tu.user_id = ga.user_id "
            "ORDER BY ga.user_id"
        ).fetchall()
        active_accounts = connection.execute(
            "SELECT tu.user_id, ga.tag "
            "FROM telegram_users tu "
            "JOIN game_accounts ga "
            "ON ga.account_id = tu.active_game_account_id "
            "ORDER BY tu.user_id"
        ).fetchall()

    assert [migration.label for migration in applied] == [
        "0008_add_game_accounts"
    ]
    expected_rows = [
        (
            row["user_id"],
            row["username"],
            row["tag"],
            *(row[column] for column in MIGRATED_DATA_COLUMNS),
        )
        for row in legacy_rows
    ]
    assert migrated_rows == expected_rows
    assert active_accounts == [(42, "Hero α"), (77, "Герой β")]


def test_game_account_migration_builds_expected_schema_and_constraints(tmp_path):
    database_path = tmp_path / "database.db"
    version_7_migrations = tmp_path / "version_7"
    prepare_version_7_database(
        database_path,
        version_7_migrations,
        [legacy_user_row(42, "telegram", "Hero", 1_000)],
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(connection, MIGRATIONS_DIR)
        columns = connection.execute("PRAGMA table_info(user_data)").fetchall()
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(user_data)"
        ).fetchall()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("telegram_users", "game_accounts", "user_data")
        }

    assert [column[1] for column in columns] == [
        "account_id",
        *MIGRATED_DATA_COLUMNS,
    ]
    assert columns[0][5] == 1
    assert all(column[3] == 1 for column in columns[1:])
    assert any(
        foreign_key[2] == "game_accounts"
        and foreign_key[3] == "account_id"
        and foreign_key[4] == "account_id"
        and foreign_key[6] == "CASCADE"
        for foreign_key in foreign_keys
    )
    assert violations == []
    assert counts == {
        "telegram_users": 1,
        "game_accounts": 1,
        "user_data": 1,
    }


def test_game_account_migration_is_idempotent_after_success(tmp_path):
    database_path = tmp_path / "database.db"
    version_7_migrations = tmp_path / "version_7"
    prepare_version_7_database(
        database_path,
        version_7_migrations,
        [legacy_user_row(42, "telegram", "Hero", 1_000)],
    )

    with sqlite3.connect(database_path) as connection:
        first_applied = apply_migrations(connection, MIGRATIONS_DIR)
        snapshot_before = connection.execute(
            "SELECT * FROM user_data"
        ).fetchall()
        second_applied = apply_migrations(connection, MIGRATIONS_DIR)
        snapshot_after = connection.execute(
            "SELECT * FROM user_data"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert [migration.version for migration in first_applied] == [8]
    assert second_applied == ()
    assert snapshot_after == snapshot_before
    assert version == 8


def test_game_account_migration_rolls_back_drop_table_on_late_failure(tmp_path):
    database_path = tmp_path / "database.db"
    version_7_migrations = tmp_path / "version_7"
    legacy_row = legacy_user_row(42, "telegram", "Hero", 1_000)
    prepare_version_7_database(
        database_path,
        version_7_migrations,
        [legacy_row],
    )

    broken_migrations = tmp_path / "broken"
    copy_initial_migrations(broken_migrations, 8)
    migration_path = broken_migrations / "0008_add_game_accounts.sql"
    migration_sql = migration_path.read_text(encoding="utf-8")
    migration_path.write_text(
        migration_sql.replace(
            "DROP TABLE user_data;",
            "DROP TABLE user_data;\n"
            "INSERT INTO deliberately_missing_table VALUES (1);",
        ),
        encoding="utf-8",
    )

    with sqlite3.connect(database_path) as connection:
        schema_before = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'user_data'"
        ).fetchone()[0]
        rows_before = connection.execute("SELECT * FROM user_data").fetchall()

        with pytest.raises(MigrationError, match="0008_add_game_accounts"):
            apply_migrations(connection, broken_migrations)

        schema_after = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'user_data'"
        ).fetchone()[0]
        rows_after = connection.execute("SELECT * FROM user_data").fetchall()
        temporary_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('telegram_users', 'game_accounts', 'user_data_v2')"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert schema_after == schema_before
    assert rows_after == rows_before
    assert temporary_tables == []
    assert version == 7


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
        connection.execute("PRAGMA user_version = 9")

        with pytest.raises(MigrationError, match="newer than supported"):
            apply_migrations(connection)
