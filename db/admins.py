from typing import Set, List, Optional

from config.config import getconf
from logger.app_logger import logger as nmd_logger
from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam
from .gapi.gsheets_manager import GSheetsManager
from .gapi.worksheet_manager import WorksheetManager
from .retry import ReconnectableDB


class Admin(Parameters):
    def __init__(self, username: str = None, user_id: int = None):
        self.username: StrParam = StrParam("Username", username)
        self.user_id: IntParam = IntParam("ID", user_id)


class AdminsDB(ReconnectableDB):
    HEADER = [Admin().params_views()]

    def __init__(self, manager: WorksheetManager = None):
        self._manager = manager or self._open_manager()
        self._admins: List[Admin] = []
        self._admins_id_set: Set[int] = set()
        self.fetch_admins(refresh=False)

    @staticmethod
    def _open_manager() -> WorksheetManager:
        ss_name = getconf("ADMINS_GTABLE_KEY")
        ws_name = getconf("ADMINS_PAGE_NAME")
        spreadsheet = GSheetsManager().open(ss_name)
        if spreadsheet.is_worksheet_exist(ws_name):
            manager = spreadsheet.get_worksheet(ws_name)
        else:
            manager = spreadsheet.add_worksheet(ws_name)
        manager.ensure_header(AdminsDB.HEADER)
        return manager

    def _reconnect(self) -> None:
        self._manager = self._open_manager()

    def add_admin(self, new_admin: Admin):
        nmd_logger.info(f"DB: add admin {new_admin.username}")
        def admin_is_missing() -> bool:
            self.fetch_admins()
            return self.get_admin(new_admin.user_id.value) is None

        if not self._add_row_with_retry(new_admin.to_row(), admin_is_missing):
            return
        self._admins.append(new_admin)
        self._admins_id_set.add(new_admin.user_id.value)

    def get_admins(self) -> List[Admin]:
        return self._admins

    def get_admin(self, user_id: int) -> Optional[Admin]:
        for admin in self._admins:
            if admin.user_id.value == user_id:
                return admin
        return None

    def is_admin(self, user_id: int):
        nmd_logger.info(f"DB: Check if {user_id} is admin")
        return user_id in self._admins_id_set

    def del_admin(self, user_id: int):
        nmd_logger.info(f"DB: del admin {user_id}")
        admins = self.get_admins()
        new_admins = [
            admin.to_row() for admin in admins if admin.user_id.value != user_id
        ]
        self._run_with_retry(lambda: self._manager.update_values(new_admins))
        self._admins = [admin for admin in admins if admin.user_id.value != user_id]
        self._admins_id_set = {admin.user_id.value for admin in self._admins}

    def fetch_admins(self, refresh: bool = True):
        nmd_logger.info("DB: fetch admins")
        def load_admins() -> List[Admin]:
            if refresh:
                self._manager.fetch()
            return [
                Admin.from_row(row) for row in self._manager.get_all_values()
            ]

        self._admins = self._run_with_retry(load_admins) or []
        self._admins_id_set: Set[int] = {admin.user_id.value for admin in self._admins}


admins_db: Optional[AdminsDB] = None


def initialize_admins_db() -> AdminsDB:
    global admins_db
    admins_db = AdminsDB()
    return admins_db


def get_admins_db() -> AdminsDB:
    if admins_db is None:
        raise RuntimeError("Admins database has not been initialized")
    return admins_db
