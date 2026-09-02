"""Clan-scoped administrator model and storage."""

from typing import List, Optional

from logger.app_logger import logger
from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam

from .access_group import AccessGroup
from .repository import DatabaseRepository


class Admin(Parameters):
    def __init__(self, username: str = None, user_id: int = None):
        super().__init__()
        self.username: StrParam = StrParam("Username", username)
        self.user_id: IntParam = IntParam("ID", user_id)


class AdminsDB(DatabaseRepository):
    def add_admin(self, admin: Admin, group_id: int) -> None:
        logger.info(
            "DB: adding admin user_id=%s username=%s group_id=%s",
            admin.user_id.value,
            admin.username.value,
            group_id,
        )

        def add(connection) -> None:
            connection.execute(
                "INSERT INTO admins (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (int(admin.user_id.value), str(admin.username.value or "")),
            )
            group_exists = connection.execute(
                "SELECT 1 FROM clans WHERE group_id = ?", (int(group_id),)
            ).fetchone()
            if group_exists is None:
                raise ValueError("Клан не найден")
            connection.execute(
                "INSERT INTO admin_clans (user_id, group_id) VALUES (?, ?) "
                "ON CONFLICT(user_id, group_id) DO NOTHING",
                (int(admin.user_id.value), int(group_id)),
            )
            connection.execute(
                "UPDATE admins SET active_group_id = COALESCE(active_group_id, ?) "
                "WHERE user_id = ?",
                (int(group_id), int(admin.user_id.value)),
            )

        self._database.run_in_transaction(add)

    def get_clan_admins(self, group_id: int) -> List[Admin]:
        rows = self._database.fetch_all(
            "SELECT a.user_id, a.username FROM admins a "
            "JOIN admin_clans ac ON ac.user_id = a.user_id "
            "WHERE ac.group_id = ? ORDER BY a.user_id",
            (int(group_id),),
        )
        return [Admin(username, user_id) for user_id, username in rows]

    def get_clan_admin(self, user_id: int, group_id: int) -> Optional[Admin]:
        row = self._database.fetch_one(
            "SELECT a.user_id, a.username FROM admins a "
            "JOIN admin_clans ac ON ac.user_id = a.user_id "
            "WHERE a.user_id = ? AND ac.group_id = ?",
            (int(user_id), int(group_id)),
        )
        return None if row is None else Admin(row[1], row[0])

    def is_clan_admin(self, user_id: int, group_id: int) -> bool:
        return self.get_clan_admin(user_id, group_id) is not None

    def has_admin_access(self, user_id: int) -> bool:
        return (
            self._database.fetch_one(
                "SELECT 1 FROM admin_clans WHERE user_id = ? LIMIT 1",
                (int(user_id),),
            )
            is not None
        )

    def get_admin_count(self) -> int:
        row = self._database.fetch_one(
            "SELECT COUNT(DISTINCT user_id) FROM admin_clans"
        )
        return 0 if row is None else int(row[0])

    def get_clans(self, user_id: int) -> List[AccessGroup]:
        rows = self._database.fetch_all(
            "SELECT c.group_id, c.title FROM clans c "
            "JOIN admin_clans ac ON ac.group_id = c.group_id "
            "WHERE ac.user_id = ? ORDER BY c.group_id",
            (int(user_id),),
        )
        return [
            AccessGroup(int(group_id), str(title)) for group_id, title in rows
        ]

    def get_active_group(self, user_id: int) -> Optional[AccessGroup]:
        row = self._database.fetch_one(
            "SELECT c.group_id, c.title FROM admins a "
            "JOIN admin_clans ac ON ac.user_id = a.user_id "
            "AND ac.group_id = a.active_group_id "
            "JOIN clans c ON c.group_id = a.active_group_id "
            "WHERE a.user_id = ?",
            (int(user_id),),
        )
        return None if row is None else AccessGroup(int(row[0]), str(row[1]))

    def select_group(self, user_id: int, group_id: int) -> None:
        def select(connection) -> None:
            membership = connection.execute(
                "SELECT 1 FROM admin_clans WHERE user_id = ? AND group_id = ?",
                (int(user_id), int(group_id)),
            ).fetchone()
            if membership is None:
                raise ValueError("Нет прав администратора этого клана")
            connection.execute(
                "UPDATE admins SET active_group_id = ? WHERE user_id = ?",
                (int(group_id), int(user_id)),
            )

        self._database.run_in_transaction(select)

    def del_clan_admin(self, user_id: int, group_id: int) -> None:
        logger.info("DB: deleting admin user_id=%s group_id=%s", user_id, group_id)

        def delete(connection) -> None:
            connection.execute(
                "DELETE FROM admin_clans WHERE user_id = ? AND group_id = ?",
                (int(user_id), int(group_id)),
            )
            remaining = connection.execute(
                "SELECT group_id FROM admin_clans WHERE user_id = ? "
                "ORDER BY group_id LIMIT 1",
                (int(user_id),),
            ).fetchone()
            if remaining is None:
                connection.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            else:
                connection.execute(
                    "UPDATE admins SET active_group_id = NULL "
                    "WHERE user_id = ? AND active_group_id = ?",
                    (int(user_id), int(group_id)),
                )

        self._database.run_in_transaction(delete)
