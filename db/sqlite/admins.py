"""SQLite-backed admins storage with Google Sheets dual-write."""

from typing import Iterable, List, Optional

from db.admins import Admin, AdminsDB as GoogleAdminsDB

from .database import SQLiteDatabase


class AdminsDB:
    def __init__(self, database: SQLiteDatabase, google: GoogleAdminsDB):
        self._database = database
        self._google = google

    def add_admin(self, admin: Admin) -> None:
        self._google.add_admin(admin)
        self.replace_all(self._google.get_admins())

    def get_admins(self) -> List[Admin]:
        rows = self._database.fetch_all(
            "SELECT user_id, username FROM admins ORDER BY user_id"
        )
        return [Admin(username, user_id) for user_id, username in rows]

    def get_admin(self, user_id: int) -> Optional[Admin]:
        row = self._database.fetch_one(
            "SELECT user_id, username FROM admins WHERE user_id = ?",
            (user_id,),
        )
        return None if row is None else Admin(row[1], row[0])

    def is_admin(self, user_id: int) -> bool:
        return self.get_admin(user_id) is not None

    def del_admin(self, user_id: int) -> None:
        self._google.del_admin(user_id)
        self.replace_all(self._google.get_admins())

    def replace_all(self, admins: Iterable[Admin]) -> None:
        rows = tuple(
            sorted(
                (
                    int(admin.user_id.value),
                    str(admin.username.value or ""),
                )
                for admin in admins
            )
        )

        def replace(connection) -> None:
            connection.execute("DELETE FROM admins")
            if rows:
                connection.executemany(
                    "INSERT INTO admins (user_id, username) VALUES (?, ?)",
                    rows,
                )

        self._database.run_in_transaction(replace)
