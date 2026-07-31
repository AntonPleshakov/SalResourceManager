from typing import Dict, List, Optional, Tuple

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.worksheet_manager import WorksheetManager
from db.retry import ReconnectableDB
from logger.app_logger import logger
from resources.user_data import EDITABLE_FIELDS, UserData


class UserDataDB(ReconnectableDB):
    def __init__(self, manager: WorksheetManager, spreadsheet_url: str = ""):
        self._manager = manager
        self._spreadsheet_url = spreadsheet_url
        self._users: Dict[int, UserData] = {}
        self.fetch()

    @classmethod
    def _open_manager(cls) -> Tuple[WorksheetManager, str]:
        spreadsheet = GSheetsManager().open(getconf("GAME_DATA_GTABLE_KEY"))
        worksheet_name = getconf("USER_DATA_PAGE_NAME")
        if spreadsheet.is_worksheet_exist(worksheet_name):
            manager = spreadsheet.get_worksheet(worksheet_name)
        else:
            manager = spreadsheet.add_worksheet(worksheet_name)
            manager.set_header([UserData().params_views()])
        return manager, spreadsheet.get_url()

    @classmethod
    def connect(cls) -> "UserDataDB":
        manager, spreadsheet_url = cls._open_manager()
        return cls(manager, spreadsheet_url)

    def _reconnect(self) -> None:
        self._manager, self._spreadsheet_url = self._open_manager()

    def fetch(self) -> None:
        logger.info("DB: fetch user resources and technologies")
        def load_users():
            self._manager.fetch()
            return [UserData.from_row(row) for row in self._manager.get_all_values()]

        users = self._run_with_retry(load_users)
        self._users = {user.user_id.value: user for user in users}

    def get_user(self, user_id: int) -> Optional[UserData]:
        return self._users.get(user_id)

    def get_users(self) -> List[UserData]:
        return list(self._users.values())

    def get_url(self) -> str:
        return self._spreadsheet_url

    def get_or_create(self, user_id: int, username: str) -> UserData:
        user = self.get_user(user_id)
        if user is not None:
            if user.username.value != username:
                user.username.value = username
                self._persist_all()
            return user

        logger.info("DB: add resource data for user %s", user_id)
        user = UserData(user_id=user_id, username=username)
        if not self._add_user(user):
            return self._users[user_id]
        self._users[user_id] = user
        return user

    def _add_user(self, user: UserData) -> bool:
        def user_is_missing() -> bool:
            self.fetch()
            return user.user_id.value not in self._users

        return self._add_row_with_retry(user.to_row(), user_is_missing)

    def set_value(
        self, user_id: int, username: str, field_name: str, value: int
    ) -> UserData:
        user = self.set_values(user_id, username, {field_name: value})
        logger.info(
            "DB: set user %s field %s to %s", user_id, field_name, value
        )
        return user

    def set_values(
        self, user_id: int, username: str, values: Dict[str, int]
    ) -> UserData:
        if not values:
            raise ValueError("At least one resource value is required")
        for field_name, value in values.items():
            if field_name not in EDITABLE_FIELDS:
                raise ValueError(f"Unknown resource field: {field_name}")
            if not isinstance(value, int) or value < 0:
                raise ValueError("Resource value must be a non-negative integer")

        user = self.get_user(user_id)
        if user is None:
            user = UserData(user_id=user_id, username=username)
            for field_name, value in values.items():
                user.set_value(field_name, value)
            if not self._add_user(user):
                return self._users[user_id]
            self._users[user_id] = user
            return user

        user.username.value = username
        for field_name, value in values.items():
            user.set_value(field_name, value)
        self._persist_all()
        logger.info("DB: set user %s fields %s", user_id, list(values))
        return user

    def _persist_all(self) -> None:
        self._run_with_retry(
            lambda: self._manager.update_values(
                [user.to_row() for user in self._users.values()]
            )
        )


user_data_db: Optional[UserDataDB] = None


def initialize_user_data_db() -> UserDataDB:
    global user_data_db
    user_data_db = UserDataDB.connect()
    return user_data_db


def get_user_data_db() -> UserDataDB:
    if user_data_db is None:
        raise RuntimeError("User data database has not been initialized")
    return user_data_db
