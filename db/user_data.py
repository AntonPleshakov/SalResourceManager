"""Game-account and resource storage."""

from datetime import date
from typing import Dict, List, Optional

from common.datetime_utils import now
from logger.app_logger import logger
from resources.user_data import (
    GameAccount,
    UPDATED_AT_FIELDS,
    UserData,
    validate_editable_field_value,
)

from .database import Database


IDENTITY_COLUMNS = ("account_id", "user_id", "username", "tag")
USER_DATA_COLUMNS = tuple(
    column for column in UserData().params() if column not in IDENTITY_COLUMNS
)
USER_DATA_TEXT_COLUMNS = frozenset(
    column for column in USER_DATA_COLUMNS if column.endswith("_updated_on")
)
QUOTED_DATA_COLUMNS = ", ".join(
    f'"{column}"' for column in ("account_id", *USER_DATA_COLUMNS)
)
DATA_PLACEHOLDERS = ", ".join("?" for _ in ("account_id", *USER_DATA_COLUMNS))
DATA_UPDATE_ASSIGNMENTS = ", ".join(
    f'"{column}" = excluded."{column}"' for column in USER_DATA_COLUMNS
)
SELECT_USER = (
    "SELECT ga.account_id, tu.user_id, tu.username, ga.tag, "
    + ", ".join(f'ud."{column}"' for column in USER_DATA_COLUMNS)
    + " FROM game_accounts ga "
      "JOIN telegram_users tu ON tu.user_id = ga.user_id "
      "JOIN user_data ud ON ud.account_id = ga.account_id "
)


class UserDataDB:
    def __init__(self, database: Database):
        self._database = database

    def get_user(
        self, user_id: int, account_id: Optional[int] = None
    ) -> Optional[UserData]:
        if account_id is None:
            row = self._database.fetch_one(
                SELECT_USER
                + "WHERE tu.user_id = ? AND "
                  "ga.account_id = tu.active_game_account_id",
                (user_id,),
            )
        else:
            row = self._database.fetch_one(
                SELECT_USER + "WHERE tu.user_id = ? AND ga.account_id = ?",
                (user_id, account_id),
            )
        return None if row is None else UserData.from_row(list(row))

    def get_users(self) -> List[UserData]:
        rows = self._database.fetch_all(
            SELECT_USER + "ORDER BY tu.user_id, ga.account_id"
        )
        return [UserData.from_row(list(row)) for row in rows]

    def get_accounts(self, user_id: int) -> List[GameAccount]:
        rows = self._database.fetch_all(
            "SELECT ga.account_id, ga.user_id, tu.username, ga.tag, "
            "ga.account_id = tu.active_game_account_id "
            "FROM game_accounts ga "
            "JOIN telegram_users tu ON tu.user_id = ga.user_id "
            "WHERE ga.user_id = ? ORDER BY ga.account_id",
            (user_id,),
        )
        return [
            GameAccount(
                account_id=int(row[0]),
                user_id=int(row[1]),
                username=str(row[2]),
                tag=str(row[3]),
                is_active=bool(row[4]),
            )
            for row in rows
        ]

    def get_active_account(self, user_id: int) -> Optional[GameAccount]:
        return next(
            (account for account in self.get_accounts(user_id) if account.is_active),
            None,
        )

    def update_username(self, user_id: int, username: str) -> None:
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "INSERT INTO telegram_users (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (user_id, username),
            )
        )

    def add_account(
        self, user_id: int, username: str, tag: str, *, make_active: bool = True
    ) -> GameAccount:
        normalized_tag = self._validate_tag(tag)

        def add(connection):
            connection.execute(
                "INSERT INTO telegram_users (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (user_id, username),
            )
            cursor = connection.execute(
                "INSERT INTO game_accounts (user_id, tag) VALUES (?, ?)",
                (user_id, normalized_tag),
            )
            account_id = int(cursor.lastrowid)
            user = UserData(
                account_id=account_id,
                user_id=user_id,
                username=username,
                tag=normalized_tag,
            )
            self._write_user(connection, user)
            has_active = connection.execute(
                "SELECT active_game_account_id FROM telegram_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
            if make_active or has_active is None:
                connection.execute(
                    "UPDATE telegram_users SET active_game_account_id = ? "
                    "WHERE user_id = ?",
                    (account_id, user_id),
                )
            return account_id

        try:
            account_id = self._database.run_in_transaction(add)
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise ValueError(
                    "Игровой аккаунт с таким nickname уже существует"
                ) from error
            raise
        logger.info(
            "DB: added game account user_id=%s account_id=%s tag=%s",
            user_id,
            account_id,
            normalized_tag,
        )
        return next(
            account
            for account in self.get_accounts(user_id)
            if account.account_id == account_id
        )

    def select_account(self, user_id: int, account_id: int) -> GameAccount:
        def select(connection):
            exists = connection.execute(
                "SELECT 1 FROM game_accounts WHERE user_id = ? AND account_id = ?",
                (user_id, account_id),
            ).fetchone()
            if exists is None:
                raise ValueError("Игровой аккаунт не найден")
            connection.execute(
                "UPDATE telegram_users SET active_game_account_id = ? "
                "WHERE user_id = ?",
                (account_id, user_id),
            )

        self._database.run_in_transaction(select)
        return self.get_active_account(user_id)  # type: ignore[return-value]

    def rename_account(
        self, user_id: int, account_id: int, tag: str
    ) -> GameAccount:
        normalized_tag = self._validate_tag(tag)
        try:
            changed = self._database.run_in_transaction(
                lambda connection: connection.execute(
                    "UPDATE game_accounts SET tag = ? "
                    "WHERE user_id = ? AND account_id = ?",
                    (normalized_tag, user_id, account_id),
                ).rowcount
            )
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise ValueError(
                    "Игровой аккаунт с таким nickname уже существует"
                ) from error
            raise
        if not changed:
            raise ValueError("Игровой аккаунт не найден")
        return next(
            account
            for account in self.get_accounts(user_id)
            if account.account_id == account_id
        )

    def delete_account(self, user_id: int, account_id: int) -> None:
        def delete(connection):
            row = connection.execute(
                "SELECT active_game_account_id FROM telegram_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            owned = connection.execute(
                "SELECT 1 FROM game_accounts WHERE user_id = ? AND account_id = ?",
                (user_id, account_id),
            ).fetchone()
            if row is None or owned is None:
                raise ValueError("Игровой аккаунт не найден")
            connection.execute(
                "DELETE FROM user_data WHERE account_id = ?", (account_id,)
            )
            connection.execute(
                "DELETE FROM game_accounts WHERE account_id = ?", (account_id,)
            )
            if row[0] == account_id:
                replacement = connection.execute(
                    "SELECT account_id FROM game_accounts WHERE user_id = ? "
                    "ORDER BY account_id LIMIT 1",
                    (user_id,),
                ).fetchone()
                connection.execute(
                    "UPDATE telegram_users SET active_game_account_id = ? "
                    "WHERE user_id = ?",
                    (None if replacement is None else replacement[0], user_id),
                )

        self._database.run_in_transaction(delete)
        logger.info(
            "DB: deleted game account user_id=%s account_id=%s",
            user_id,
            account_id,
        )

    def get_or_create(
        self, user_id: int, username: str, tag: Optional[str] = None
    ) -> UserData:
        self.update_username(user_id, username)
        user = self.get_user(user_id)
        if user is None:
            account = self.add_account(user_id, username, tag or username)
            user = self.get_user(user_id, account.account_id)
        return user  # type: ignore[return-value]

    def set_value(
        self,
        user_id: int,
        username: str,
        field_name: str,
        value: int,
        updated_on: Optional[date] = None,
        tag: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> UserData:
        user = self.set_values(
            user_id,
            username,
            {field_name: value},
            updated_on=updated_on,
            tag=tag,
            account_id=account_id,
        )
        logger.info(
            "DB: updated user_id=%s account_id=%s field=%s",
            user_id,
            user.account_id.value,
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
        account_id: Optional[int] = None,
    ) -> UserData:
        self._validate_values(values)
        self.update_username(user_id, username)
        field_updated_on = updated_on or now().date()
        user = self.get_user(user_id, account_id)
        if user is None:
            if account_id is not None:
                raise ValueError("Игровой аккаунт не найден")
            user = self.get_or_create(user_id, username, tag)
        user.username.value = username
        for field_name, value in values.items():
            user.set_value(field_name, value)
            if field_name in UPDATED_AT_FIELDS:
                user.mark_updated(field_name, field_updated_on)
        self._save(user)
        return user

    @staticmethod
    def _validate_tag(tag: str) -> str:
        normalized = " ".join((tag or "").split())
        if not normalized:
            raise ValueError("Nickname не может быть пустым")
        if len(normalized) > 64:
            raise ValueError("Nickname не может быть длиннее 64 символов")
        return normalized

    @staticmethod
    def _validate_values(values: Dict[str, int]) -> None:
        if not values:
            raise ValueError("At least one resource value is required")
        for field_name, value in values.items():
            validate_editable_field_value(field_name, value)

    def _save(self, user: UserData) -> None:
        self._database.run_in_transaction(
            lambda connection: self._write_user(connection, user)
        )

    @staticmethod
    def _write_user(connection, user: UserData) -> None:
        row = [int(user.account_id.value)]
        for column in USER_DATA_COLUMNS:
            value = getattr(user, column).value
            if column in USER_DATA_TEXT_COLUMNS:
                row.append(str(value or ""))
            else:
                row.append(int(value))
        connection.execute(
            f"INSERT INTO user_data ({QUOTED_DATA_COLUMNS}) "
            f"VALUES ({DATA_PLACEHOLDERS}) "
            f"ON CONFLICT(account_id) DO UPDATE SET {DATA_UPDATE_ASSIGNMENTS}",
            tuple(row),
        )
