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
        nmd_logger.debug("DB: opening admins worksheet")
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
        nmd_logger.info("DB: reconnecting admins storage")
        self._manager = self._open_manager()

    def add_admin(self, new_admin: Admin):
        nmd_logger.info(
            "DB: adding admin user_id=%s username=%s",
            new_admin.user_id.value,
            new_admin.username.value,
        )

        def admin_is_missing() -> bool:
            self.fetch_admins()
            return self.get_admin(new_admin.user_id.value) is None

        if not self._add_row_with_retry(new_admin.to_row(), admin_is_missing):
            nmd_logger.info(
                "DB: admin user_id=%s username=%s was already present after reconnect",
                new_admin.user_id.value,
                new_admin.username.value,
            )
            return
        self._admins.append(new_admin)
        self._admins_id_set.add(new_admin.user_id.value)
        nmd_logger.info("DB: admin added; total=%d", len(self._admins))

    def get_admins(self) -> List[Admin]:
        return self._admins

    def get_admin(self, user_id: int) -> Optional[Admin]:
        for admin in self._admins:
            if admin.user_id.value == user_id:
                return admin
        return None

    def is_admin(self, user_id: int):
        result = user_id in self._admins_id_set
        admin = self.get_admin(user_id)
        username = admin.username.value if admin is not None else "<not-an-admin>"
        nmd_logger.debug(
            "DB: admin check user_id=%s username=%s result=%s",
            user_id,
            username,
            result,
        )
        return result

    def del_admin(self, user_id: int):
        admin = self.get_admin(user_id)
        username = admin.username.value if admin is not None else "<not-found>"
        nmd_logger.info(
            "DB: deleting admin user_id=%s username=%s", user_id, username
        )
        admins = self.get_admins()
        new_admins = [
            admin.to_row() for admin in admins if admin.user_id.value != user_id
        ]
        self._run_with_retry(lambda: self._manager.update_values(new_admins))
        self._admins = [admin for admin in admins if admin.user_id.value != user_id]
        self._admins_id_set = {admin.user_id.value for admin in self._admins}
        nmd_logger.info("DB: admin deleted; total=%d", len(self._admins))

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
        nmd_logger.info("DB: fetched %d admins", len(self._admins))


admins_db: Optional[AdminsDB] = None


def initialize_admins_db() -> AdminsDB:
    global admins_db
    admins_db = AdminsDB()
    nmd_logger.debug("DB: admins singleton initialized")
    return admins_db


def set_admins_db(database) -> None:
    global admins_db
    admins_db = database


def get_admins_db() -> AdminsDB:
    if admins_db is None:
        nmd_logger.error("DB: admins requested before initialization")
        raise RuntimeError("Admins database has not been initialized")
    return admins_db
