"""SQLite-backed user-data storage."""

from datetime import date
from typing import Dict, List, Optional

from common.datetime_utils import now
from logger.app_logger import logger
from resources.user_data import (
    UPDATED_AT_FIELDS,
    UserData,
    validate_editable_field_value,
)

from .database import SQLiteDatabase


USER_DATA_COLUMNS = tuple(UserData().params())
USER_DATA_TEXT_COLUMNS = frozenset(
    {"username", "tag"}
    | {
        name
        for name in USER_DATA_COLUMNS
        if name.endswith("_updated_on")
    }
)
QUOTED_USER_DATA_COLUMNS = ", ".join(
    f'"{column}"' for column in USER_DATA_COLUMNS
)
USER_DATA_PLACEHOLDERS = ", ".join("?" for _ in USER_DATA_COLUMNS)
USER_DATA_UPDATE_ASSIGNMENTS = ", ".join(
    f'"{column}" = excluded."{column}"'
    for column in USER_DATA_COLUMNS
    if column != "user_id"
)


class UserDataDB:
    def __init__(self, database: SQLiteDatabase):
        self._database = database

    def get_user(self, user_id: int) -> Optional[UserData]:
        row = self._database.fetch_one(
            f"SELECT {QUOTED_USER_DATA_COLUMNS} "
            "FROM user_data WHERE user_id = ?",
            (user_id,),
        )
        return None if row is None else UserData.from_row(list(row))

    def get_users(self) -> List[UserData]:
        rows = self._database.fetch_all(
            f"SELECT {QUOTED_USER_DATA_COLUMNS} "
            "FROM user_data ORDER BY user_id"
        )
        return [UserData.from_row(list(row)) for row in rows]

    def get_or_create(
        self, user_id: int, username: str, tag: Optional[str] = None
    ) -> UserData:
        user = self.get_user(user_id)
        if user is None:
            logger.info(
                "DB: adding resource data for user_id=%s username=%s tag=%s",
                user_id,
                username,
                tag or "",
            )
            user = UserData(user_id=user_id, username=username, tag=tag or "")
            self._save(user)
            return user

        if user.username.value != username or (
            tag is not None and user.tag.value != tag
        ):
            user.username.value = username
            if tag is not None:
                user.tag.value = tag
            self._save(user)
        return user

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
        user = self.get_user(user_id) or UserData(
            user_id=user_id,
            username=username,
            tag=tag or "",
        )
        user.username.value = username
        if tag is not None:
            user.tag.value = tag
        for field_name, value in values.items():
            user.set_value(field_name, value)
            if field_name in UPDATED_AT_FIELDS:
                user.mark_updated(field_name, field_updated_on)
        self._save(user)
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
            raise ValueError("At least one resource value is required")
        for field_name, value in values.items():
            validate_editable_field_value(field_name, value)

    def _save(self, user: UserData) -> None:
        row = []
        for column in USER_DATA_COLUMNS:
            value = getattr(user, column).value
            if column in USER_DATA_TEXT_COLUMNS:
                row.append(str(value or ""))
            else:
                row.append(int(value))
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                f"INSERT INTO user_data ({QUOTED_USER_DATA_COLUMNS}) "
                f"VALUES ({USER_DATA_PLACEHOLDERS}) "
                f"ON CONFLICT(user_id) DO UPDATE SET "
                f"{USER_DATA_UPDATE_ASSIGNMENTS}",
                tuple(row),
            )
        )
