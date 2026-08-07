"""SQLite-backed user-data storage with Google Sheets dual-write."""

from datetime import date
from typing import Dict, Iterable, List, Optional

from db.user_data import UserDataDB as GoogleUserDataDB
from resources.user_data import UserData

from .database import SQLiteDatabase


USER_DATA_COLUMNS = tuple(UserData().params())
USER_DATA_TEXT_COLUMNS = frozenset(
    {"username", "tag"}
    | {
        name
        for name in USER_DATA_COLUMNS
        if name.endswith("_updated_on")
    }
)
QUOTED_USER_DATA_COLUMNS = ", ".join(
    f'"{column}"' for column in USER_DATA_COLUMNS
)


class UserDataDB:
    def __init__(self, database: SQLiteDatabase, google: GoogleUserDataDB):
        self._database = database
        self._google = google

    def get_user(self, user_id: int) -> Optional[UserData]:
        row = self._database.fetch_one(
            f"SELECT {QUOTED_USER_DATA_COLUMNS} "
            "FROM user_data WHERE user_id = ?",
            (user_id,),
        )
        return None if row is None else UserData.from_row(list(row))

    def get_users(self) -> List[UserData]:
        rows = self._database.fetch_all(
            f"SELECT {QUOTED_USER_DATA_COLUMNS} "
            "FROM user_data ORDER BY user_id"
        )
        return [UserData.from_row(list(row)) for row in rows]

    def get_url(self) -> str:
        return self._google.get_url()

    def get_or_create(
        self, user_id: int, username: str, tag: Optional[str] = None
    ) -> UserData:
        self._google.get_or_create(user_id, username, tag)
        return self._sync_and_get(user_id)

    def set_value(
        self,
        user_id: int,
        username: str,
        field_name: str,
        value: int,
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData:
        self._google.set_value(
            user_id,
            username,
            field_name,
            value,
            updated_on=updated_on,
            tag=tag,
        )
        return self._sync_and_get(user_id)

    def set_values(
        self,
        user_id: int,
        username: str,
        values: Dict[str, int],
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData:
        self._google.set_values(
            user_id,
            username,
            values,
            updated_on=updated_on,
            tag=tag,
        )
        return self._sync_and_get(user_id)

    def _sync_and_get(self, user_id: int) -> UserData:
        self.replace_all(self._google.get_users())
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError(
                f"User {user_id} is missing after SQLite synchronization"
            )
        return user

    def replace_all(self, users: Iterable[UserData]) -> None:
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
        rows = tuple(sorted(rows))
        placeholders = ", ".join("?" for _ in USER_DATA_COLUMNS)

        def replace(connection) -> None:
            connection.execute("DELETE FROM user_data")
            if rows:
                connection.executemany(
                    f"INSERT INTO user_data ({QUOTED_USER_DATA_COLUMNS}) "
                    f"VALUES ({placeholders})",
                    rows,
                )

        self._database.run_in_transaction(replace)
