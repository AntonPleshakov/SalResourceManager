"""SQLite-backed release-view storage with Google Sheets dual-write."""

from typing import Dict, Mapping, Optional

from db.release_views import ReleaseViewsDB as GoogleReleaseViewsDB

from .database import SQLiteDatabase


class ReleaseViewsDB:
    def __init__(self, database: SQLiteDatabase, google: GoogleReleaseViewsDB):
        self._database = database
        self._google = google

    def get_last_seen_version(self, user_id: int) -> Optional[str]:
        row = self._database.fetch_one(
            "SELECT last_seen_version FROM release_views WHERE user_id = ?",
            (user_id,),
        )
        return None if row is None else row[0]

    def get_users_count(self) -> int:
        row = self._database.fetch_one("SELECT COUNT(*) FROM release_views")
        return row[0]

    def get_users(self) -> Dict[int, tuple[str, str]]:
        rows = self._database.fetch_all(
            "SELECT user_id, username, last_seen_version "
            "FROM release_views ORDER BY user_id"
        )
        return {
            user_id: (username, last_seen_version)
            for user_id, username, last_seen_version in rows
        }

    def update_username(self, user_id: int, username: str) -> None:
        self._google.update_username(user_id, username)
        self.replace_all(self._google.get_users())

    def mark_seen(self, user_id: int, username: str, version: str) -> None:
        self._google.mark_seen(user_id, username, version)
        self.replace_all(self._google.get_users())

    def replace_all(
        self,
        release_views: Mapping[int, tuple[str, str]],
    ) -> None:
        rows = tuple(
            sorted(
                (
                    int(user_id),
                    str(username or ""),
                    str(version),
                )
                for user_id, (username, version) in release_views.items()
            )
        )

        def replace(connection) -> None:
            connection.execute("DELETE FROM release_views")
            if rows:
                connection.executemany(
                    "INSERT INTO release_views "
                    "(user_id, username, last_seen_version) VALUES (?, ?, ?)",
                    rows,
                )

        self._database.run_in_transaction(replace)
