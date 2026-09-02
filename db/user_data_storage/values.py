from datetime import date
from typing import Dict, Optional

from common.datetime_utils import now
from logger.app_logger import logger
from resources.user_data import UPDATED_AT_FIELDS, UserData, validate_editable_field_value

from db.user_data_storage.schema import write_user


def _validate_values(values: Dict[str, int]) -> None:
    if not values:
        raise ValueError("At least one resource value is required")
    for field_name, value in values.items():
        validate_editable_field_value(field_name, value)


class UserDataValues:
    _database: object

    def _save_user(self, user: UserData) -> None:
        self._database.run_in_transaction(
            lambda connection: write_user(connection, user)
        )

    def get_or_create(
        self,
        user_id: int,
        username: str,
        tag: Optional[str] = None,
        clan_id: Optional[int] = None,
    ) -> UserData:
        self.update_username(user_id, username)
        user = self.get_assigned_user(user_id)
        if user is None:
            account = self.add_account(
                user_id,
                username,
                tag or username,
                clan_id=clan_id,
            )
            user = self.get_assigned_user(user_id, account.account_id)
        return user  # type: ignore[return-value]

    def set_values(
        self,
        user_id: int,
        username: str,
        values: Dict[str, int],
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
        account_id: Optional[int] = None,
        clan_id: Optional[int] = None,
    ) -> UserData:
        _validate_values(values)
        self.update_username(user_id, username)
        field_updated_on = updated_on or now().date()
        user = self.get_assigned_user(user_id, account_id)
        if user is None:
            if account_id is not None:
                raise ValueError("Игровой аккаунт не найден")
            user = self.get_or_create(user_id, username, tag, clan_id)
        user.username.value = username
        for field_name, value in values.items():
            user.set_value(field_name, value)
            if field_name in UPDATED_AT_FIELDS:
                user.mark_updated(field_name, field_updated_on)
        self._save_user(user)
        return user

    def set_value(
        self,
        user_id: int,
        username: str,
        field_name: str,
        value: int,
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
        account_id: Optional[int] = None,
        clan_id: Optional[int] = None,
    ) -> UserData:
        user = self.set_values(
            user_id,
            username,
            {field_name: value},
            updated_on=updated_on,
            tag=tag,
            account_id=account_id,
            clan_id=clan_id,
        )
        logger.info(
            "DB: updated user_id=%s account_id=%s field=%s",
            user_id,
            user.account_id.value,
            field_name,
        )
        return user
