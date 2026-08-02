from datetime import date
from typing import Dict, List, Optional, Tuple

from common.datetime_utils import now
from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.worksheet_manager import WorksheetManager
from db.retry import ReconnectableDB
from logger.app_logger import logger
from resources.user_data import EDITABLE_FIELDS, UPDATED_AT_FIELDS, UserData


USER_DATA_SCHEMA_VERSION = 2
LEGACY_V1_HEADER = [
    "Telegram ID",
    "Пользователь",
    "Ключи маунтов",
    "Билетики навыков",
    "Скорлупа",
    "Молотки",
    "Гемы",
    "Питомцы",
    "Необъединённые маунты",
    "Уровень кузницы",
    "Снижение стоимости призыва навыков (%)",
    "Доп. шанс на яйцо",
    "Снижение стоимости призыва маунта (%)",
    "Шанс на доп. маунта",
]
LEGACY_COLUMN_ALIASES = {"Питомцы и яйца": "Питомцы"}
class UserDataDB(ReconnectableDB):
    HEADER = [UserData().params_views()]

    def __init__(self, manager: WorksheetManager, spreadsheet_url: str = ""):
        self._manager = manager
        self._spreadsheet_url = spreadsheet_url
        self._users: Dict[int, UserData] = {}
        self.fetch(refresh=False)

    @classmethod
    def _open_manager(cls) -> Tuple[WorksheetManager, str]:
        logger.debug("DB: opening user data worksheet")
        spreadsheet = GSheetsManager().open(getconf("GAME_DATA_GTABLE_KEY"))
        worksheet_name = getconf("USER_DATA_PAGE_NAME")
        if spreadsheet.is_worksheet_exist(worksheet_name):
            manager = spreadsheet.get_worksheet(worksheet_name)
        else:
            manager = spreadsheet.add_worksheet(worksheet_name)
        cls._migrate_schema(manager)
        return manager, spreadsheet.get_url()

    @classmethod
    def _schema_version(cls, header: List[str]) -> int:
        if header == cls.HEADER[0]:
            return USER_DATA_SCHEMA_VERSION
        if header == LEGACY_V1_HEADER:
            return 1
        return 0

    @classmethod
    def _migrate_schema(cls, manager: WorksheetManager) -> None:
        header_rows = manager.get_header()
        header = header_rows[0] if header_rows else []
        rows = manager.get_all_values()

        # Some old worksheets have a header row but no frozen rows.
        if not header and rows and rows[0][:1] == ["Telegram ID"]:
            header, rows = rows[0], rows[1:]
        elif not header and rows:
            raise RuntimeError(
                "Cannot migrate user data worksheet without a recognizable header"
            )

        current_version = cls._schema_version(header)
        if current_version != USER_DATA_SCHEMA_VERSION:
            logger.info(
                "DB: migrating user data schema from version=%d to version=%d",
                current_version,
                USER_DATA_SCHEMA_VERSION,
            )
            source_indexes = {title: index for index, title in enumerate(header)}

            def source_index(column: str) -> Optional[int]:
                return source_indexes.get(
                    column,
                    source_indexes.get(LEGACY_COLUMN_ALIASES.get(column)),
                )

            migrated_rows = [
                [
                    row[index]
                    if (index := source_index(column)) is not None
                    and index < len(row)
                    else ""
                    for column in cls.HEADER[0]
                ]
                for row in rows
            ]
            manager.set_header(cls.HEADER)
            if migrated_rows:
                manager.update_values(migrated_rows)
        else:
            manager.ensure_header(cls.HEADER)

        for index, parameter_name in enumerate(UserData().params()):
            if parameter_name.endswith("_updated_on"):
                manager.hide_column(index)

    @classmethod
    def connect(cls) -> "UserDataDB":
        logger.info("DB: connecting user data storage")
        manager, spreadsheet_url = cls._open_manager()
        return cls(manager, spreadsheet_url)

    def _reconnect(self) -> None:
        logger.info("DB: reconnecting user data storage")
        self._manager, self._spreadsheet_url = self._open_manager()

    def fetch(self, refresh: bool = True) -> None:
        logger.info("DB: fetch user resources and technologies")
        def load_users():
            if refresh:
                self._manager.fetch()
            return [UserData.from_row(row) for row in self._manager.get_all_values()]

        users = self._run_with_retry(load_users)
        self._users = {user.user_id.value: user for user in users}
        logger.info("DB: fetched resource data for %d users", len(self._users))

    def get_user(self, user_id: int) -> Optional[UserData]:
        return self._users.get(user_id)

    def get_users(self) -> List[UserData]:
        return list(self._users.values())

    def get_url(self) -> str:
        return self._spreadsheet_url

    def get_or_create(
        self, user_id: int, username: str, tag: Optional[str] = None
    ) -> UserData:
        user = self.get_user(user_id)
        if user is not None:
            if user.username.value != username or (
                tag is not None and user.tag.value != tag
            ):
                logger.debug(
                    "DB: updating user identity for user_id=%s username=%s tag=%s",
                    user_id,
                    username,
                    tag,
                )
                user.username.value = username
                if tag is not None:
                    user.tag.value = tag
                self._persist_all()
            return user

        logger.info(
            "DB: adding resource data for user_id=%s username=%s tag=%s",
            user_id,
            username,
            tag,
        )
        user = UserData(user_id=user_id, username=username, tag=tag or "")
        if not self._add_user(user):
            logger.info(
                "DB: user_id=%s username=%s tag=%s was already present after reconnect",
                user_id,
                username,
                tag or "",
            )
            return self._users[user_id]
        self._users[user_id] = user
        logger.info("DB: resource user added; total=%d", len(self._users))
        return user

    def _add_user(self, user: UserData) -> bool:
        def user_is_missing() -> bool:
            self.fetch()
            return user.user_id.value not in self._users

        return self._add_row_with_retry(user.to_row(), user_is_missing)

    def set_value(
        self,
        user_id: int,
        username: str,
        field_name: str,
        value: int,
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData:
        user = self.set_values(
            user_id,
            username,
            {field_name: value},
            updated_on=updated_on,
            tag=tag,
        )
        logger.info(
            "DB: updated user_id=%s username=%s tag=%s field=%s",
            user_id,
            username,
            tag or "",
            field_name,
        )
        return user

    def set_values(
        self,
        user_id: int,
        username: str,
        values: Dict[str, int],
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
    ) -> UserData:
        self._validate_values(values)
        field_updated_on = updated_on or now().date()

        user = self.get_user(user_id)
        if user is None:
            user = UserData(user_id=user_id, username=username, tag=tag or "")
            for field_name, value in values.items():
                user.set_value(field_name, value)
                if field_name in UPDATED_AT_FIELDS:
                    user.mark_updated(field_name, field_updated_on)
            if not self._add_user(user):
                logger.info(
                    "DB: user_id=%s username=%s tag=%s was already present while saving fields",
                    user_id,
                    username,
                    tag or "",
                )
                return self._users[user_id]
            self._users[user_id] = user
            logger.info(
                "DB: created user_id=%s username=%s tag=%s with fields=%s",
                user_id,
                username,
                tag or "",
                sorted(values),
            )
            return user

        user.username.value = username
        if tag is not None:
            user.tag.value = tag
        for field_name, value in values.items():
            user.set_value(field_name, value)
            if field_name in UPDATED_AT_FIELDS:
                user.mark_updated(field_name, field_updated_on)
        self._persist_all()
        logger.info(
            "DB: updated user_id=%s username=%s tag=%s fields=%s",
            user_id,
            username,
            tag or "",
            sorted(values),
        )
        return user

    @staticmethod
    def _validate_values(values: Dict[str, int]) -> None:
        if not values:
            logger.warning("DB: rejected empty user data update")
            raise ValueError("At least one resource value is required")
        for field_name, value in values.items():
            if field_name not in EDITABLE_FIELDS:
                logger.warning("DB: rejected unknown user data field=%s", field_name)
                raise ValueError(f"Unknown user data field: {field_name}")
            if not isinstance(value, int) or value < 0:
                logger.warning("DB: rejected invalid value for field=%s", field_name)
                raise ValueError("Resource value must be a non-negative integer")
            if field_name == "forge_level" and not 1 <= value <= 35:
                raise ValueError("Forge level must be between 1 and 35")
            if field_name == "skill_summon_cost" and not 0 <= value <= 25:
                raise ValueError("Skill summon cost reduction must be between 0 and 25")
            if field_name == "mount_summon_cost" and not 0 <= value <= 25:
                raise ValueError("Mount summon cost reduction must be between 0 and 25")
            if field_name == "extra_mount_chance" and not 0 <= value <= 50:
                raise ValueError("Extra mount chance must be between 0 and 50")

    def _persist_all(self) -> None:
        logger.debug("DB: persisting resource data for %d users", len(self._users))
        self._run_with_retry(
            lambda: self._manager.update_values(
                [user.to_row() for user in self._users.values()]
            )
        )


user_data_db: Optional[UserDataDB] = None


def initialize_user_data_db() -> UserDataDB:
    global user_data_db
    user_data_db = UserDataDB.connect()
    logger.debug("DB: user data singleton initialized")
    return user_data_db


def get_user_data_db() -> UserDataDB:
    if user_data_db is None:
        logger.error("DB: user data requested before initialization")
        raise RuntimeError("User data database has not been initialized")
    return user_data_db
