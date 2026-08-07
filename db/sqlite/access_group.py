"""SQLite-backed access-group storage with Google Sheets dual-write."""

from typing import Optional

from db.access_group import AccessGroupDB as GoogleAccessGroupDB

from .database import SQLiteDatabase


class AccessGroupDB:
    def __init__(self, database: SQLiteDatabase, google: GoogleAccessGroupDB):
        self._database = database
        self._google = google

    def get_group_id(self) -> Optional[int]:
        row = self._database.fetch_one(
            "SELECT group_id FROM access_group WHERE singleton = 1"
        )
        return None if row is None else row[0]

    def set_group_id(self, group_id: int) -> None:
        self._google.set_group_id(group_id)
        self.replace(self._google.get_group_id())

    def replace(self, group_id: Optional[int]) -> None:
        def replace(connection) -> None:
            connection.execute("DELETE FROM access_group")
            if group_id is not None:
                connection.execute(
                    "INSERT INTO access_group (singleton, group_id) VALUES (1, ?)",
                    (int(group_id),),
                )

        self._database.run_in_transaction(replace)
