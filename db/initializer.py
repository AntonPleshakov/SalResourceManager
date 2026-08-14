"""Create and expose the application's database storages."""

import atexit
from dataclasses import dataclass
from pathlib import Path

from logger.app_logger import logger

from .access_group import AccessGroupDB
from .admins import AdminsDB
from .database import Database
from .release_views import ReleaseViewsDB
from .user_data import UserDataDB


DEFAULT_DATABASE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "sal_resources.db"
)


@dataclass(frozen=True)
class Databases:
    database: Database
    admins: AdminsDB
    access_group: AccessGroupDB
    release_views: ReleaseViewsDB
    user_data: UserDataDB


_databases: Databases | None = None


def initialize_database(
    *,
    database_path: Path | None = None,
) -> Databases:
    global _databases
    database_path = database_path or DEFAULT_DATABASE_PATH
    database = None

    logger.info(
        "SQLite initialization started before application writes: path=%s",
        database_path,
    )
    try:
        database = Database(database_path)
        databases = Databases(
            database=database,
            admins=AdminsDB(database),
            access_group=AccessGroupDB(database),
            release_views=ReleaseViewsDB(database),
            user_data=UserDataDB(database),
        )
    except Exception:
        if database is not None:
            database.close()
        raise

    _databases = databases
    atexit.register(database.close)
    logger.info("Database storages initialized")
    return databases


def get_databases() -> Databases:
    if _databases is None:
        logger.error("DB requested before initialization")
        raise RuntimeError("Database has not been initialized")
    return _databases


def get_admins_db() -> AdminsDB:
    return get_databases().admins


def get_access_group_db() -> AccessGroupDB:
    return get_databases().access_group


def get_release_views_db() -> ReleaseViewsDB:
    return get_databases().release_views


def get_user_data_db() -> UserDataDB:
    return get_databases().user_data
