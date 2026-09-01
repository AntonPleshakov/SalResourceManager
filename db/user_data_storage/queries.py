from typing import Dict, List, Optional

from resources.user_data import GameAccount, UserData

from db.user_data_storage.schema import SELECT_USER


def _users_from_rows(rows) -> List[UserData]:
    return [UserData.from_row(list(row)) for row in rows]


class UserDataQueries:
    _database: object

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

    def get_users(self, clan_id: Optional[int] = None) -> List[UserData]:
        where = "" if clan_id is None else "WHERE ga.clan_id = ? "
        parameters = () if clan_id is None else (int(clan_id),)
        rows = self._database.fetch_all(
            SELECT_USER + where + "ORDER BY tu.user_id, ga.account_id",
            parameters,
        )
        return _users_from_rows(rows)

    def get_users_with_reminders_enabled(
        self, clan_id: Optional[int] = None
    ) -> List[UserData]:
        clan_filter = "" if clan_id is None else "AND ga.clan_id = ? "
        parameters = () if clan_id is None else (int(clan_id),)
        rows = self._database.fetch_all(
            SELECT_USER
            + "WHERE tu.reminders_enabled = 1 "
            + clan_filter
            + "ORDER BY tu.user_id, ga.account_id",
            parameters,
        )
        return _users_from_rows(rows)

    def get_account_counts(self) -> Dict[int, int]:
        rows = self._database.fetch_all(
            "SELECT user_id, COUNT(*) FROM game_accounts "
            "GROUP BY user_id ORDER BY user_id"
        )
        return {int(user_id): int(count) for user_id, count in rows}

    def get_clan_account_counts(self) -> List[tuple[int, str, int, int]]:
        rows = self._database.fetch_all(
            "SELECT c.group_id, c.title, COUNT(DISTINCT ga.user_id), "
            "COUNT(ga.account_id) FROM clans c "
            "LEFT JOIN game_accounts ga ON ga.clan_id = c.group_id "
            "GROUP BY c.group_id, c.title ORDER BY c.title, c.group_id"
        )
        return [
            (int(group_id), str(title), int(user_count), int(account_count))
            for group_id, title, user_count, account_count in rows
        ]

    def get_accounts(self, user_id: int) -> List[GameAccount]:
        rows = self._database.fetch_all(
            "SELECT ga.account_id, ga.user_id, tu.username, ga.tag, "
            "ga.account_id = tu.active_game_account_id, ga.clan_id, c.title "
            "FROM game_accounts ga "
            "JOIN telegram_users tu ON tu.user_id = ga.user_id "
            "JOIN clans c ON c.group_id = ga.clan_id "
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
                clan_id=int(row[5]),
                clan_title=str(row[6]),
            )
            for row in rows
        ]

    def get_active_account(self, user_id: int) -> Optional[GameAccount]:
        return next(
            (account for account in self.get_accounts(user_id) if account.is_active),
            None,
        )
