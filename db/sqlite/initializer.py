"""Apply SQLite migrations and activate table storages."""

import atexit
from dataclasses import dataclass
from pathlib import Path

from config.config import getconf_path
from db.access_group import set_access_group_db
from db.admins import set_admins_db
from db.release_views import set_release_views_db
from db.user_data import set_user_data_db
from logger.app_logger import logger

from .access_group import AccessGroupDB
from .admins import AdminsDB
from .database import SQLiteDatabase
from .release_views import ReleaseViewsDB
from .user_data import UserDataDB


DEFAULT_DATABASE_PATH = "data/sal_resources.db"


@dataclass(frozen=True)
class SQLiteDatabases:
    database: SQLiteDatabase
    admins: AdminsDB
    access_group: AccessGroupDB
    release_views: ReleaseViewsDB
    user_data: UserDataDB


def initialize_sqlite_databases(
    *,
    database_path: Path | None = None,
) -> SQLiteDatabases:
    database_path = database_path or getconf_path(
        "SQLITE_DB_PATH",
        DEFAULT_DATABASE_PATH,
    )
    database = None

    logger.info(
        "SQLite initialization started before application writes: path=%s",
        database_path,
    )
    try:
        database = SQLiteDatabase(database_path)
        databases = SQLiteDatabases(
            database=database,
            admins=AdminsDB(database),
            access_group=AccessGroupDB(database),
            release_views=ReleaseViewsDB(database),
            user_data=UserDataDB(database),
        )
        _activate(databases)
    except Exception:
        if database is not None:
            database.close()
        raise

    atexit.register(database.close)
    logger.info("SQLite databases activated")
    return databases


def _activate(databases: SQLiteDatabases) -> None:
    set_admins_db(databases.admins)
    set_access_group_db(databases.access_group)
    set_release_views_db(databases.release_views)
    set_user_data_db(databases.user_data)
