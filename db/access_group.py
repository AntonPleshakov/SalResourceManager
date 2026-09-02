"""Registered clan storage."""

from dataclasses import dataclass
from typing import List, Optional

from logger.app_logger import logger

from .repository import DatabaseRepository


@dataclass(frozen=True)
class AccessGroup:
    group_id: int
    title: str


class GroupAlreadyRegisteredError(ValueError):
    pass


class ExistingClanAdminRequiredError(ValueError):
    pass


def _normalized_group_title(group_id: int, title: str) -> str:
    return " ".join((title or "").split()) or f"Клан {group_id}"


def _insert_group(connection, group_id: int, title: str) -> AccessGroup:
    normalized_title = _normalized_group_title(group_id, title)
    cursor = connection.execute(
        "INSERT OR IGNORE INTO clans "
        "(group_id, title, title_needs_sync) VALUES (?, ?, 0)",
        (int(group_id), normalized_title),
    )
    if cursor.rowcount == 0:
        raise GroupAlreadyRegisteredError("Группа уже зарегистрирована")
    return AccessGroup(int(group_id), normalized_title)


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

    def get_spreadsheet_id(self, group_id: int) -> Optional[str]:
        row = self._database.fetch_one(
            "SELECT spreadsheet_id FROM clans WHERE group_id = ?",
            (int(group_id),),
        )
        if row is None:
            raise ValueError("Клан не найден")
        return None if row[0] is None else str(row[0])

    def set_spreadsheet_id(self, group_id: int, spreadsheet_id: str) -> None:
        normalized_id = str(spreadsheet_id or "").strip()
        if not normalized_id:
            raise ValueError("Не указан идентификатор Google Таблицы")

        def save(connection) -> None:
            row = connection.execute(
                "SELECT spreadsheet_id FROM clans WHERE group_id = ?",
                (int(group_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Клан не найден")
            if row[0] is not None and str(row[0]) != normalized_id:
                raise ValueError("Для клана уже настроена другая Google Таблица")
            connection.execute(
                "UPDATE clans SET spreadsheet_id = ? WHERE group_id = ?",
                (normalized_id, int(group_id)),
            )

        try:
            self._database.run_in_transaction(save)
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise ValueError(
                    "Эта Google Таблица уже привязана к другому клану"
                ) from error
            raise

    def get_groups_requiring_title_sync(self) -> List[AccessGroup]:
        rows = self._database.fetch_all(
            "SELECT group_id, title FROM clans "
            "WHERE title_needs_sync = 1 ORDER BY group_id"
        )
        return [AccessGroup(int(group_id), str(title)) for group_id, title in rows]

    def add_group(self, group_id: int, title: str) -> AccessGroup:
        normalized_title = _normalized_group_title(group_id, title)
        logger.info(
            "DB: registering clan group_id=%s title=%s",
            group_id,
            normalized_title,
        )
        return self._database.run_in_transaction(
            lambda connection: _insert_group(
                connection, group_id, normalized_title
            )
        )

    def register_group(
        self,
        group_id: int,
        title: str,
        user_id: int,
        username: str,
        *,
        require_existing_clan_admin: bool,
    ) -> AccessGroup:
        def register(connection) -> AccessGroup:
            if require_existing_clan_admin:
                existing_access = connection.execute(
                    "SELECT 1 FROM admin_clans WHERE user_id = ? LIMIT 1",
                    (int(user_id),),
                ).fetchone()
                if existing_access is None:
                    raise ExistingClanAdminRequiredError(
                        "Нет прав администратора существующего клана"
                    )
            group = _insert_group(connection, group_id, title)
            connection.execute(
                "INSERT INTO admins (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (int(user_id), str(username or "")),
            )
            connection.execute(
                "INSERT INTO admin_clans (user_id, group_id) VALUES (?, ?)",
                (int(user_id), int(group_id)),
            )
            connection.execute(
                "UPDATE admins SET active_group_id = ? WHERE user_id = ?",
                (int(group_id), int(user_id)),
            )
            return group

        return self._database.run_in_transaction(register)

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
