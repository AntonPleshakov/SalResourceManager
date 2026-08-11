"""Administrator model and storage."""

from typing import List, Optional

from logger.app_logger import logger
from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam

from .database import Database


class Admin(Parameters):
    def __init__(self, username: str = None, user_id: int = None):
        self.username: StrParam = StrParam("Username", username)
        self.user_id: IntParam = IntParam("ID", user_id)


class AdminsDB:
    def __init__(self, database: Database):
        self._database = database

    def add_admin(self, admin: Admin) -> None:
        logger.info(
            "DB: adding admin user_id=%s username=%s",
            admin.user_id.value,
            admin.username.value,
        )

        def add(connection) -> None:
            connection.execute(
                "INSERT INTO admins (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (int(admin.user_id.value), str(admin.username.value or "")),
            )

        self._database.run_in_transaction(add)

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
        logger.info("DB: deleting admin user_id=%s", user_id)
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "DELETE FROM admins WHERE user_id = ?",
                (user_id,),
            )
        )
