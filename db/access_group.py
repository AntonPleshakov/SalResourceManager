from typing import Optional, Protocol

from logger.app_logger import logger


class AccessGroupDB(Protocol):
    def get_group_id(self) -> Optional[int]: ...

    def set_group_id(self, group_id: int) -> None: ...


access_group_db: Optional[AccessGroupDB] = None


def set_access_group_db(database: AccessGroupDB) -> None:
    global access_group_db
    access_group_db = database


def get_access_group_db() -> AccessGroupDB:
    if access_group_db is None:
        logger.error("DB: access group requested before initialization")
        raise RuntimeError("Access group database has not been initialized")
    return access_group_db
