from typing import Dict, Optional

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.worksheet_manager import WorksheetManager
from db.retry import ReconnectableDB
from logger.app_logger import logger


RELEASE_VIEWS_WORKSHEET_NAME = "Bot users"
LEGACY_RELEASE_VIEWS_HEADER = [["Telegram ID", "Last seen version"]]
RELEASE_VIEWS_HEADER = [["Telegram ID", "Username", "Last seen version"]]


class ReleaseViewsDB(ReconnectableDB):
    def __init__(self, manager: Optional[WorksheetManager] = None):
        self._manager = manager or self._open_manager()
        if manager is not None:
            self._ensure_schema(manager)
        self._users: Dict[int, tuple[str, str]] = {}
        self.fetch(refresh=False)

    @classmethod
    def _open_manager(cls) -> WorksheetManager:
        logger.debug("DB: opening release views worksheet")
        spreadsheet = GSheetsManager().open(getconf("ADMINS_GTABLE_KEY"))
        if spreadsheet.is_worksheet_exist(RELEASE_VIEWS_WORKSHEET_NAME):
            manager = spreadsheet.get_worksheet(RELEASE_VIEWS_WORKSHEET_NAME)
        else:
            manager = spreadsheet.add_worksheet(RELEASE_VIEWS_WORKSHEET_NAME)
        cls._ensure_schema(manager)
        return manager

    @staticmethod
    def _ensure_schema(manager: WorksheetManager) -> None:
        header = manager.get_header()
        rows = manager.get_all_values()
        legacy_rows = None
        if header == LEGACY_RELEASE_VIEWS_HEADER:
            legacy_rows = rows
        elif not header and rows[:1] == LEGACY_RELEASE_VIEWS_HEADER:
            legacy_rows = rows[1:]

        if legacy_rows is not None:
            logger.info("DB: migrating release views schema to include username")
            manager.set_header(RELEASE_VIEWS_HEADER)
            manager.update_values(
                [
                    [row[0], "", row[1]]
                    for row in legacy_rows
                    if len(row) >= 2
                ]
            )
            return

        manager.ensure_header(RELEASE_VIEWS_HEADER)

    def _reconnect(self) -> None:
        logger.info("DB: reconnecting release views storage")
        self._manager = self._open_manager()

    def fetch(self, refresh: bool = True) -> None:
        logger.info("DB: fetch release views")

        def load_users() -> Dict[int, tuple[str, str]]:
            if refresh:
                self._manager.fetch()
            users: Dict[int, tuple[str, str]] = {}
            for row in self._manager.get_all_values():
                if len(row) < 3 or not row[0] or not row[2]:
                    continue
                try:
                    users[int(row[0])] = (row[1], row[2])
                except ValueError:
                    logger.warning("DB: skipped invalid release view row=%s", row)
            return users

        self._users = self._run_with_retry(load_users) or {}
        logger.info("DB: fetched release views for %d users", len(self._users))

    def get_last_seen_version(self, user_id: int) -> Optional[str]:
        user = self._users.get(user_id)
        return user[1] if user is not None else None

    def get_users_count(self) -> int:
        return len(self._users)

    def get_users(self) -> Dict[int, tuple[str, str]]:
        return dict(self._users)

    def _persist_users(self, users: Dict[int, tuple[str, str]]) -> None:
        rows = [
            [str(stored_user_id), stored_username, stored_version]
            for stored_user_id, (stored_username, stored_version) in users.items()
        ]
        self._run_with_retry(lambda: self._manager.update_values(rows))
        self._users = users

    def update_username(self, user_id: int, username: str) -> None:
        user = self._users.get(user_id)
        if user is None or user[0] == username:
            return

        users = dict(self._users)
        users[user_id] = (username, user[1])
        self._persist_users(users)
        logger.info(
            "DB: updated release view username for user_id=%s username=%s",
            user_id,
            username,
        )

    def mark_seen(self, user_id: int, username: str, version: str) -> None:
        if self._users.get(user_id) == (username, version):
            return

        users = dict(self._users)
        users[user_id] = (username, version)
        self._persist_users(users)
        logger.info(
            "DB: marked release version=%s as seen by user_id=%s username=%s",
            version,
            user_id,
            username,
        )


release_views_db: Optional[ReleaseViewsDB] = None


def initialize_release_views_db() -> ReleaseViewsDB:
    global release_views_db
    release_views_db = ReleaseViewsDB()
    logger.debug("DB: release views singleton initialized")
    return release_views_db


def set_release_views_db(database) -> None:
    global release_views_db
    release_views_db = database


def get_release_views_db() -> ReleaseViewsDB:
    if release_views_db is None:
        logger.error("DB: release views requested before initialization")
        raise RuntimeError("Release views database has not been initialized")
    return release_views_db
