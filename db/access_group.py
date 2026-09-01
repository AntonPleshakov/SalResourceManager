"""Registered clan storage."""

from dataclasses import dataclass
from typing import List, Optional

from logger.app_logger import logger

from .repository import DatabaseRepository


@dataclass(frozen=True)
class AccessGroup:
    group_id: int
    title: str


class AccessGroupDB(DatabaseRepository):
    def get_groups(self) -> List[AccessGroup]:
        rows = self._database.fetch_all(
            "SELECT group_id, title FROM clans ORDER BY title, group_id"
        )
        return [AccessGroup(int(group_id), str(title)) for group_id, title in rows]

    def get_group(self, group_id: int) -> Optional[AccessGroup]:
        row = self._database.fetch_one(
            "SELECT group_id, title FROM clans WHERE group_id = ?",
            (int(group_id),),
        )
        return None if row is None else AccessGroup(int(row[0]), str(row[1]))

    def get_groups_requiring_title_sync(self) -> List[AccessGroup]:
        rows = self._database.fetch_all(
            "SELECT group_id, title FROM clans "
            "WHERE title_needs_sync = 1 ORDER BY group_id"
        )
        return [AccessGroup(int(group_id), str(title)) for group_id, title in rows]

    def add_group(self, group_id: int, title: str) -> AccessGroup:
        normalized_title = " ".join((title or "").split()) or f"Клан {group_id}"
        logger.info(
            "DB: registering clan group_id=%s title=%s",
            group_id,
            normalized_title,
        )
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "INSERT INTO clans (group_id, title, title_needs_sync) "
                "VALUES (?, ?, 0) "
                "ON CONFLICT(group_id) DO UPDATE SET "
                "title = excluded.title, title_needs_sync = 0",
                (int(group_id), normalized_title),
            )
        )
        return AccessGroup(int(group_id), normalized_title)

    def rename_group(self, group_id: int, title: str) -> AccessGroup:
        normalized_title = " ".join((title or "").split())
        if not normalized_title:
            raise ValueError("Название клана не может быть пустым")

        def rename(connection):
            cursor = connection.execute(
                "UPDATE clans SET title = ?, title_needs_sync = 0 "
                "WHERE group_id = ?",
                (normalized_title, int(group_id)),
            )
            if cursor.rowcount == 0:
                raise ValueError("Клан не зарегистрирован")

        self._database.run_in_transaction(rename)
        logger.info("DB: renamed clan group_id=%s title=%s", group_id, normalized_title)
        return AccessGroup(int(group_id), normalized_title)
