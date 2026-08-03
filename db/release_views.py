from typing import Dict, Optional

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.worksheet_manager import WorksheetManager
from db.retry import ReconnectableDB
from logger.app_logger import logger


RELEASE_VIEWS_WORKSHEET_NAME = "Bot users"
RELEASE_VIEWS_HEADER = [["Telegram ID", "Last seen version"]]


class ReleaseViewsDB(ReconnectableDB):
    def __init__(self, manager: Optional[WorksheetManager] = None):
        self._manager = manager or self._open_manager()
        self._versions: Dict[int, str] = {}
        self.fetch(refresh=False)

    @staticmethod
    def _open_manager() -> WorksheetManager:
        logger.debug("DB: opening release views worksheet")
        spreadsheet = GSheetsManager().open(getconf("ADMINS_GTABLE_KEY"))
        if spreadsheet.is_worksheet_exist(RELEASE_VIEWS_WORKSHEET_NAME):
            manager = spreadsheet.get_worksheet(RELEASE_VIEWS_WORKSHEET_NAME)
        else:
            manager = spreadsheet.add_worksheet(RELEASE_VIEWS_WORKSHEET_NAME)
        manager.ensure_header(RELEASE_VIEWS_HEADER)
        return manager

    def _reconnect(self) -> None:
        logger.info("DB: reconnecting release views storage")
        self._manager = self._open_manager()

    def fetch(self, refresh: bool = True) -> None:
        logger.info("DB: fetch release views")

        def load_versions() -> Dict[int, str]:
            if refresh:
                self._manager.fetch()
            versions: Dict[int, str] = {}
            for row in self._manager.get_all_values():
                if len(row) < 2 or not row[0] or not row[1]:
                    continue
                try:
                    versions[int(row[0])] = row[1]
                except ValueError:
                    logger.warning("DB: skipped invalid release view row=%s", row)
            return versions

        self._versions = self._run_with_retry(load_versions) or {}
        logger.info("DB: fetched release views for %d users", len(self._versions))

    def get_last_seen_version(self, user_id: int) -> Optional[str]:
        return self._versions.get(user_id)

    def get_users_count(self) -> int:
        return len(self._versions)

    def mark_seen(self, user_id: int, version: str) -> None:
        if self._versions.get(user_id) == version:
            return

        versions = dict(self._versions)
        versions[user_id] = version
        rows = [
            [str(stored_user_id), stored_version]
            for stored_user_id, stored_version in versions.items()
        ]
        self._run_with_retry(lambda: self._manager.update_values(rows))
        self._versions = versions
        logger.info(
            "DB: marked release version=%s as seen by user_id=%s",
            version,
            user_id,
        )


release_views_db: Optional[ReleaseViewsDB] = None


def initialize_release_views_db() -> ReleaseViewsDB:
    global release_views_db
    release_views_db = ReleaseViewsDB()
    logger.debug("DB: release views singleton initialized")
    return release_views_db


def get_release_views_db() -> ReleaseViewsDB:
    if release_views_db is None:
        logger.error("DB: release views requested before initialization")
        raise RuntimeError("Release views database has not been initialized")
    return release_views_db
