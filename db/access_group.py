"""Access-group storage."""

from typing import Optional

from logger.app_logger import logger

from .database import Database


class AccessGroupDB:
    def __init__(self, database: Database):
        self._database = database

    def get_group_id(self) -> Optional[int]:
        row = self._database.fetch_one(
            "SELECT group_id FROM access_group WHERE singleton = 1"
        )
        return None if row is None else row[0]

    def set_group_id(self, group_id: int) -> None:
        logger.info("DB: set access group to %s", group_id)
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "INSERT INTO access_group (singleton, group_id) VALUES (1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET group_id = excluded.group_id",
                (int(group_id),),
            )
        )
