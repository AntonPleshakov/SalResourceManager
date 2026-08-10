from typing import List, Optional, Protocol

from logger.app_logger import logger
from parameters import Parameters
from parameters.int_param import IntParam
from parameters.str_param import StrParam


class Admin(Parameters):
    def __init__(self, username: str = None, user_id: int = None):
        self.username: StrParam = StrParam("Username", username)
        self.user_id: IntParam = IntParam("ID", user_id)


class AdminsDB(Protocol):
    def add_admin(self, admin: Admin) -> None: ...

    def get_admins(self) -> List[Admin]: ...

    def get_admin(self, user_id: int) -> Optional[Admin]: ...

    def is_admin(self, user_id: int) -> bool: ...

    def del_admin(self, user_id: int) -> None: ...


admins_db: Optional[AdminsDB] = None


def set_admins_db(database: AdminsDB) -> None:
    global admins_db
    admins_db = database


def get_admins_db() -> AdminsDB:
    if admins_db is None:
        logger.error("DB: admins requested before initialization")
        raise RuntimeError("Admins database has not been initialized")
    return admins_db
