from datetime import date
from typing import Dict, List, Optional, Protocol

from logger.app_logger import logger
from resources.user_data import UserData


class UserDataDB(Protocol):
    def get_user(self, user_id: int) -> Optional[UserData]: ...

    def get_users(self) -> List[UserData]: ...

    def get_or_create(
        self,
        user_id: int,
        username: str,
        tag: Optional[str] = None,
    ) -> UserData: ...

    def set_value(
        self,
        user_id: int,
        username: str,
        field_name: str,
        value: int,
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData: ...

    def set_values(
        self,
        user_id: int,
        username: str,
        values: Dict[str, int],
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData: ...


user_data_db: Optional[UserDataDB] = None


def set_user_data_db(database: UserDataDB) -> None:
    global user_data_db
    user_data_db = database


def get_user_data_db() -> UserDataDB:
    if user_data_db is None:
        logger.error("DB: user data requested before initialization")
        raise RuntimeError("User data database has not been initialized")
    return user_data_db
