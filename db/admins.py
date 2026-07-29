from typing import Set, List, Optional

from config.config import getconf
from logger.app_logger import logger as nmd_logger
from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam
from .gapi.gsheets_manager import GSheetsManager
from .gapi.worksheet_manager import WorksheetManager


class Admin(Parameters):
    def __init__(self, username: str = None, user_id: int = None):
        self.username: StrParam = StrParam("Username", username)
        self.user_id: IntParam = IntParam("ID", user_id)


class AdminsDB:
    def __init__(self):
        ss_name = getconf("ADMINS_GTABLE_KEY")
        ws_name = getconf("ADMINS_PAGE_NAME")

        self._manager: WorksheetManager = (
            GSheetsManager().open(ss_name).get_worksheet(ws_name)
        )
        self._admins: List[Admin] = []
        self._admins_id_set: Set[int] = set()
        self.fetch_admins()

    def add_admin(self, new_admin: Admin):
        nmd_logger.info(f"DB: add admin {new_admin.username}")
        self._manager.add_row(new_admin.to_row())
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
        self._manager.update_values(new_admins)
        self._admins = [admin for admin in admins if admin.user_id.value != user_id]
        self._admins_id_set = {admin.user_id.value for admin in self._admins}

    def fetch_admins(self):
        nmd_logger.info("DB: fetch admins")
        self._manager.fetch()
        admins_matrix = self._manager.get_all_values()
        self._admins: List[Admin] = [Admin.from_row(row) for row in admins_matrix]
        self._admins_id_set: Set[int] = {admin.user_id.value for admin in self._admins}


admins_db = AdminsDB()
