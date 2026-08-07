"""Stage 1 startup import and activation of Google/SQLite dual-write."""

import atexit
from pathlib import Path

from config.config import getconf_path
from db.access_group import AccessGroupDB
from db.admins import AdminsDB
from db.release_views import ReleaseViewsDB
from db.user_data import UserDataDB
from db.war_stages import WarStagesDB
from logger.app_logger import logger

from .mirror import SQLiteMirror


DEFAULT_DATABASE_PATH = "data/sal_resources.db"


def initialize_sqlite_stage_one(
    admins_db: AdminsDB,
    access_group_db: AccessGroupDB,
    release_views_db: ReleaseViewsDB,
    user_data_db: UserDataDB,
    war_stages_db: WarStagesDB,
    *,
    database_path: Path | None = None,
) -> SQLiteMirror:
    database_path = database_path or getconf_path(
        "SQLITE_DB_PATH",
        DEFAULT_DATABASE_PATH,
    )
    mirror = None

    logger.info(
        "SQLite stage 1 import started before application writes: path=%s",
        database_path,
    )
    try:
        mirror = SQLiteMirror(database_path)
        mirror.import_from_google(
            admins=admins_db.get_admins(),
            access_group_id=access_group_db.get_group_id(),
            release_views=release_views_db.get_users(),
            users=user_data_db.get_users(),
            war_stages=war_stages_db.get_stages(),
        )
        _enable_dual_write(
            mirror,
            admins_db,
            access_group_db,
            release_views_db,
            user_data_db,
            war_stages_db,
        )
    except Exception:
        if mirror is not None:
            mirror.close()
        raise

    atexit.register(mirror.close)
    logger.info(
        "SQLite stage 1 import completed; reads=google writes=google+sqlite"
    )
    return mirror


def _enable_dual_write(
    mirror: SQLiteMirror,
    admins_db: AdminsDB,
    access_group_db: AccessGroupDB,
    release_views_db: ReleaseViewsDB,
    user_data_db: UserDataDB,
    war_stages_db: WarStagesDB,
) -> None:
    admins_db.enable_sqlite_mirror(
        lambda: mirror.replace_admins(admins_db.get_admins())
    )
    access_group_db.enable_sqlite_mirror(
        lambda: mirror.replace_access_group(access_group_db.get_group_id())
    )
    release_views_db.enable_sqlite_mirror(
        lambda: mirror.replace_release_views(release_views_db.get_users())
    )
    user_data_db.enable_sqlite_mirror(
        lambda: mirror.replace_user_data(user_data_db.get_users())
    )
    war_stages_db.enable_sqlite_mirror(
        lambda: mirror.replace_war_stages(war_stages_db.get_stages())
    )
