"""Apply SQLite migrations and activate table storages."""

import atexit
from dataclasses import dataclass
from pathlib import Path

from config.config import getconf_path
from db.access_group import (
    AccessGroupDB as GoogleAccessGroupDB,
    set_access_group_db,
)
from db.admins import AdminsDB as GoogleAdminsDB, set_admins_db
from db.release_views import (
    ReleaseViewsDB as GoogleReleaseViewsDB,
    set_release_views_db,
)
from db.user_data import UserDataDB as GoogleUserDataDB, set_user_data_db
from db.war_stages import (
    WarStagesDB as GoogleWarStagesDB,
    set_war_stages_db,
)
from logger.app_logger import logger

from .access_group import AccessGroupDB
from .admins import AdminsDB
from .database import SQLiteDatabase
from .release_views import ReleaseViewsDB
from .user_data import UserDataDB
from .war_stages import WarStagesDB


DEFAULT_DATABASE_PATH = "data/sal_resources.db"


@dataclass(frozen=True)
class SQLiteDatabases:
    database: SQLiteDatabase
    admins: AdminsDB
    access_group: AccessGroupDB
    release_views: ReleaseViewsDB
    user_data: UserDataDB
    war_stages: WarStagesDB


def initialize_sqlite_databases(
    admins_db: GoogleAdminsDB,
    access_group_db: GoogleAccessGroupDB,
    release_views_db: GoogleReleaseViewsDB,
    user_data_db: GoogleUserDataDB,
    war_stages_db: GoogleWarStagesDB,
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
            admins=AdminsDB(database, admins_db),
            access_group=AccessGroupDB(database, access_group_db),
            release_views=ReleaseViewsDB(database, release_views_db),
            user_data=UserDataDB(database, user_data_db),
            war_stages=WarStagesDB(database, war_stages_db),
        )
        _activate(databases)
    except Exception:
        if database is not None:
            database.close()
        raise

    atexit.register(database.close)
    logger.info(
        "SQLite databases activated: reads=sqlite writes=google+sqlite"
    )
    return databases


def _activate(databases: SQLiteDatabases) -> None:
    set_admins_db(databases.admins)
    set_access_group_db(databases.access_group)
    set_release_views_db(databases.release_views)
    set_user_data_db(databases.user_data)
    set_war_stages_db(databases.war_stages)
