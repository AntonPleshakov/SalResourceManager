from typing import Optional

from logger.app_logger import logger
from resources.user_data import GameAccount, UserData

from db.user_data_storage.schema import write_user


def _resolve_clan_id(connection, clan_id: Optional[int]) -> int:
    if clan_id is not None:
        exists = connection.execute(
            "SELECT 1 FROM clans WHERE group_id = ?", (int(clan_id),)
        ).fetchone()
        if exists is None:
            raise ValueError("Клан не найден")
        return int(clan_id)

    rows = connection.execute("SELECT group_id FROM clans").fetchall()
    if len(rows) != 1:
        raise ValueError("Выберите клан игрового аккаунта")
    return int(rows[0][0])


def _validate_tag(tag: str) -> str:
    normalized = " ".join((tag or "").split())
    if not normalized:
        raise ValueError("Имя аккаунта не может быть пустым")
    if len(normalized) > 64:
        raise ValueError("Имя аккаунта не может быть длиннее 64 символов")
    return normalized


def _translate_unique_tag_error(error: Exception) -> None:
    if "UNIQUE constraint failed" in str(error):
        raise ValueError(
            "Игровой аккаунт с таким именем уже существует"
        ) from error


class AccountCommands:
    _database: object

    def add_account(
        self,
        user_id: int,
        username: str,
        tag: str,
        *,
        clan_id: Optional[int] = None,
        make_active: bool = True,
    ) -> GameAccount:
        normalized_tag = _validate_tag(tag)

        def add(connection):
            resolved_clan_id = _resolve_clan_id(connection, clan_id)
            connection.execute(
                "INSERT INTO telegram_users (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (user_id, username),
            )
            cursor = connection.execute(
                "INSERT INTO game_accounts (user_id, clan_id, tag) VALUES (?, ?, ?)",
                (user_id, resolved_clan_id, normalized_tag),
            )
            account_id = int(cursor.lastrowid)
            write_user(
                connection,
                UserData(
                    account_id=account_id,
                    user_id=user_id,
                    username=username,
                    tag=normalized_tag,
                ),
            )
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
            _translate_unique_tag_error(error)
            raise
        logger.info(
            "DB: added game account user_id=%s account_id=%s clan_id=%s tag=%s",
            user_id,
            account_id,
            clan_id,
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
        normalized_tag = _validate_tag(tag)
        try:
            changed = self._database.run_in_transaction(
                lambda connection: connection.execute(
                    "UPDATE game_accounts SET tag = ? "
                    "WHERE user_id = ? AND account_id = ?",
                    (normalized_tag, user_id, account_id),
                ).rowcount
            )
        except Exception as error:
            _translate_unique_tag_error(error)
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
            if row[0] == account_id:
                raise ValueError("Активный аккаунт нельзя удалить")
            connection.execute(
                "DELETE FROM user_data WHERE account_id = ?", (account_id,)
            )
            connection.execute(
                "DELETE FROM game_accounts WHERE account_id = ?", (account_id,)
            )

        self._database.run_in_transaction(delete)
        logger.info(
            "DB: deleted game account user_id=%s account_id=%s",
            user_id,
            account_id,
        )
