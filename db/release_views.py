from typing import Dict, Optional, Protocol

from logger.app_logger import logger


class ReleaseViewsDB(Protocol):
    def get_last_seen_version(self, user_id: int) -> Optional[str]: ...

    def get_users_count(self) -> int: ...

    def get_users(self) -> Dict[int, tuple[str, str]]: ...

    def update_username(self, user_id: int, username: str) -> None: ...

    def mark_seen(self, user_id: int, username: str, version: str) -> None: ...


release_views_db: Optional[ReleaseViewsDB] = None


def set_release_views_db(database: ReleaseViewsDB) -> None:
    global release_views_db
    release_views_db = database


def get_release_views_db() -> ReleaseViewsDB:
    if release_views_db is None:
        logger.error("DB: release views requested before initialization")
        raise RuntimeError("Release views database has not been initialized")
    return release_views_db
