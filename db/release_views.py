"""Release-view storage."""

from typing import Dict, Optional

from logger.app_logger import logger

from .database import Database


class ReleaseViewsDB:
    def __init__(self, database: Database):
        self._database = database

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
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "UPDATE release_views SET username = ? WHERE user_id = ?",
                (str(username or ""), int(user_id)),
            )
        )

    def mark_seen(self, user_id: int, username: str, version: str) -> None:
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "INSERT INTO release_views "
                "(user_id, username, last_seen_version) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "username = excluded.username, "
                "last_seen_version = excluded.last_seen_version",
                (int(user_id), str(username or ""), str(version)),
            )
        )
        logger.info(
            "DB: marked release version=%s as seen by user_id=%s username=%s",
            version,
            user_id,
            username,
        )
