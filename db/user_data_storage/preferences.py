from logger.app_logger import logger


class UserPreferences:
    _database: object

    def reminders_enabled(self, user_id: int) -> bool:
        row = self._database.fetch_one(
            "SELECT reminders_enabled FROM telegram_users WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            raise ValueError("Telegram user not found")
        return bool(row[0])

    def set_reminders_enabled(self, user_id: int, enabled: bool) -> None:
        changed = self._database.run_in_transaction(
            lambda connection: connection.execute(
                "UPDATE telegram_users SET reminders_enabled = ? WHERE user_id = ?",
                (int(enabled), user_id),
            ).rowcount
        )
        if not changed:
            raise ValueError("Telegram user not found")
        logger.info(
            "DB: reminders enabled=%s for user_id=%s",
            enabled,
            user_id,
        )

    def update_username(self, user_id: int, username: str) -> None:
        self._database.run_in_transaction(
            lambda connection: connection.execute(
                "INSERT INTO telegram_users (user_id, username) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
                (user_id, username),
            )
        )
