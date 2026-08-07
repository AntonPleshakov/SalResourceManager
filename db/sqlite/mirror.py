"""Schema management and typed snapshots for the SQLite mirror."""

import sqlite3
import threading
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from resources.user_data import UserData

from .migration_runner import apply_migrations

USER_DATA_COLUMNS = tuple(UserData().params())
USER_DATA_TEXT_COLUMNS = frozenset(
    {"username", "tag"}
    | {name for name in USER_DATA_COLUMNS if name.endswith("_updated_on")}
)
TABLE_COLUMNS = {
    "admins": ("user_id", "username"),
    "access_group": ("singleton", "group_id"),
    "release_views": ("user_id", "username", "last_seen_version"),
    "user_data": USER_DATA_COLUMNS,
    "war_stages": ("day", "activity_1", "activity_2", "activity_3"),
}
TABLE_TYPES = {
    "admins": ("INTEGER", "TEXT"),
    "access_group": ("INTEGER", "INTEGER"),
    "release_views": ("INTEGER", "TEXT", "TEXT"),
    "user_data": tuple(
        "TEXT" if column in USER_DATA_TEXT_COLUMNS else "INTEGER"
        for column in USER_DATA_COLUMNS
    ),
    "war_stages": ("INTEGER", "TEXT", "TEXT", "TEXT"),
}

Rows = Tuple[tuple, ...]


class SQLiteSchemaError(RuntimeError):
    """The SQLite file is corrupt or has an unexpected schema."""


class SQLiteMirror:
    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )
        try:
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._initialize_schema()
        except Exception:
            self._connection.close()
            raise

    def _initialize_schema(self) -> None:
        with self._lock:
            check = self._connection.execute("PRAGMA quick_check").fetchone()
            if check != ("ok",):
                raise SQLiteSchemaError(f"SQLite quick_check failed: {check!r}")

            apply_migrations(self._connection)
            for table, expected_columns in TABLE_COLUMNS.items():
                rows = self._connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
                actual_columns = tuple(row[1] for row in rows)
                if actual_columns != expected_columns:
                    raise SQLiteSchemaError(
                        f"Unexpected columns for {table}: {actual_columns!r}; "
                        f"expected {expected_columns!r}"
                    )
                actual_types = tuple(row[2].upper() for row in rows)
                if actual_types != TABLE_TYPES[table]:
                    raise SQLiteSchemaError(
                        f"Unexpected column types for {table}: {actual_types!r}; "
                        f"expected {TABLE_TYPES[table]!r}"
                    )
                primary_key = tuple(row[1] for row in rows if row[5])
                if primary_key != expected_columns[:1]:
                    raise SQLiteSchemaError(
                        f"Unexpected primary key for {table}: {primary_key!r}; "
                        f"expected {expected_columns[:1]!r}"
                    )
                actual_not_null = tuple(bool(row[3]) for row in rows)
                expected_not_null = (False,) + (True,) * (
                    len(expected_columns) - 1
                )
                if actual_not_null != expected_not_null:
                    raise SQLiteSchemaError(
                        f"Unexpected nullability for {table}: "
                        f"{actual_not_null!r}; expected {expected_not_null!r}"
                    )

    def import_from_google(
        self,
        *,
        admins: Iterable,
        access_group_id: int | None,
        release_views: Mapping[int, tuple[str, str]],
        users: Iterable[UserData],
        war_stages: Mapping[int, Sequence],
    ) -> Dict[str, int]:
        snapshots = {
            "admins": self._admin_rows(admins),
            "access_group": self._access_group_rows(access_group_id),
            "release_views": self._release_view_rows(release_views),
            "user_data": self._user_data_rows(users),
            "war_stages": self._war_stage_rows(war_stages),
        }
        with self._lock, self._connection:
            for table, rows in snapshots.items():
                self._replace_and_verify(table, rows)
        return {table: len(rows) for table, rows in snapshots.items()}

    def replace_admins(self, admins: Iterable) -> None:
        self._replace_table("admins", self._admin_rows(admins))

    def replace_access_group(self, group_id: int | None) -> None:
        self._replace_table("access_group", self._access_group_rows(group_id))

    def replace_release_views(
        self, release_views: Mapping[int, tuple[str, str]]
    ) -> None:
        self._replace_table(
            "release_views",
            self._release_view_rows(release_views),
        )

    def replace_user_data(self, users: Iterable[UserData]) -> None:
        self._replace_table("user_data", self._user_data_rows(users))

    def replace_war_stages(self, war_stages: Mapping[int, Sequence]) -> None:
        self._replace_table("war_stages", self._war_stage_rows(war_stages))

    def _replace_table(self, table: str, rows: Rows) -> None:
        with self._lock, self._connection:
            self._replace_and_verify(table, rows)

    def _replace_and_verify(self, table: str, rows: Rows) -> None:
        columns = TABLE_COLUMNS[table]
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        self._connection.execute(f'DELETE FROM "{table}"')
        if rows:
            self._connection.executemany(
                f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
                rows,
            )
        stored_rows = tuple(
            self._connection.execute(
                f'SELECT {quoted_columns} FROM "{table}" '
                f'ORDER BY "{columns[0]}"'
            ).fetchall()
        )
        if stored_rows != rows:
            raise RuntimeError(f"SQLite verification failed for table {table}")

    @staticmethod
    def _admin_rows(admins: Iterable) -> Rows:
        return tuple(
            sorted(
                (
                    int(admin.user_id.value),
                    str(admin.username.value or ""),
                )
                for admin in admins
            )
        )

    @staticmethod
    def _access_group_rows(group_id: int | None) -> Rows:
        return () if group_id is None else ((1, int(group_id)),)

    @staticmethod
    def _release_view_rows(
        release_views: Mapping[int, tuple[str, str]],
    ) -> Rows:
        return tuple(
            sorted(
                (
                    int(user_id),
                    str(username or ""),
                    str(version),
                )
                for user_id, (username, version) in release_views.items()
            )
        )

    @staticmethod
    def _user_data_rows(users: Iterable[UserData]) -> Rows:
        rows = []
        for user in users:
            row = []
            for column in USER_DATA_COLUMNS:
                value = getattr(user, column).value
                if column in USER_DATA_TEXT_COLUMNS:
                    row.append(str(value or ""))
                else:
                    row.append(int(value))
            rows.append(tuple(row))
        return tuple(sorted(rows))

    @staticmethod
    def _war_stage_rows(war_stages: Mapping[int, Sequence]) -> Rows:
        return tuple(
            (
                int(day),
                *(str(activity.value) for activity in activities),
            )
            for day, activities in sorted(war_stages.items())
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
