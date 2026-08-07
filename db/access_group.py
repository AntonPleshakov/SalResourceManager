from typing import Optional

from config.config import getconf
from logger.app_logger import logger
from .gapi.gsheets_manager import GSheetsManager
from .gapi.worksheet_manager import WorksheetManager
from .retry import ReconnectableDB


SETTINGS_WORKSHEET_NAME = "Settings"
ACCESS_GROUP_ID_KEY = "Access group ID"
SETTINGS_HEADER = [["Setting", "Value"]]


class AccessGroupDB(ReconnectableDB):
    def __init__(self, manager: WorksheetManager = None):
        self._manager = manager or self._open_manager()
        self._group_id: Optional[int] = None
        self.fetch(refresh=False)

    @staticmethod
    def _open_manager() -> WorksheetManager:
        logger.debug("DB: opening access group worksheet")
        spreadsheet = GSheetsManager().open(getconf("ADMINS_GTABLE_KEY"))
        if spreadsheet.is_worksheet_exist(SETTINGS_WORKSHEET_NAME):
            manager = spreadsheet.get_worksheet(SETTINGS_WORKSHEET_NAME)
        else:
            manager = spreadsheet.add_worksheet(SETTINGS_WORKSHEET_NAME)
        manager.ensure_header(SETTINGS_HEADER)
        return manager

    def _reconnect(self) -> None:
        logger.info("DB: reconnecting access group storage")
        self._manager = self._open_manager()

    def fetch(self, refresh: bool = True) -> None:
        logger.info("DB: fetch access group")

        def load_group_id() -> Optional[int]:
            if refresh:
                self._manager.fetch()
            for row in self._manager.get_all_values():
                if len(row) >= 2 and row[0] == ACCESS_GROUP_ID_KEY:
                    return int(row[1])
            return None

        self._group_id = self._run_with_retry(load_group_id)
        logger.info(
            "DB: access group fetched; configured=%s", self._group_id is not None
        )

    def get_group_id(self) -> Optional[int]:
        return self._group_id

    def set_group_id(self, group_id: int) -> None:
        logger.info("DB: set access group to %s", group_id)
        values = [[ACCESS_GROUP_ID_KEY, str(group_id)]]
        self._run_with_retry(lambda: self._manager.update_values(values))
        self._group_id = group_id


access_group_db: Optional[AccessGroupDB] = None


def initialize_access_group_db() -> AccessGroupDB:
    global access_group_db
    access_group_db = AccessGroupDB()
    logger.debug("DB: access group singleton initialized")
    return access_group_db


def set_access_group_db(database) -> None:
    global access_group_db
    access_group_db = database


def get_access_group_db() -> AccessGroupDB:
    if access_group_db is None:
        logger.error("DB: access group requested before initialization")
        raise RuntimeError("Access group database has not been initialized")
    return access_group_db
