from telebot import TeleBot

from db.access_group import AccessGroup
from db.admins import AdminsDB
from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.clans import is_group_member


class AdminAccessError(ValueError):
    pass


class AdminAccessCheckError(AdminAccessError):
    pass


def require_admin_access(
    bot: TeleBot,
    user_id: int,
    group_id: int,
    admins: AdminsDB | None = None,
) -> None:
    database = admins or get_admins_db()
    if not database.is_clan_admin(user_id, group_id):
        raise AdminAccessError("Нет прав администратора выбранного клана")
    try:
        member = bot.get_chat_member(group_id, user_id)
    except Exception as error:
        logger.warning(
            "Unable to verify clan admin membership user_id=%s group_id=%s: %s",
            user_id,
            group_id,
            type(error).__name__,
        )
        raise AdminAccessCheckError(
            "Не удалось проверить участие администратора в клане"
        ) from error
    if not is_group_member(member):
        database.del_clan_admin(user_id, group_id)
        raise AdminAccessError("Администратор больше не состоит в выбранном клане")


def get_current_admin_clans(
    bot: TeleBot,
    user_id: int,
    admins: AdminsDB | None = None,
) -> list[AccessGroup]:
    database = admins or get_admins_db()
    current_groups = []
    for group in database.get_clans(user_id):
        try:
            require_admin_access(bot, user_id, group.group_id, database)
        except AdminAccessCheckError:
            raise
        except AdminAccessError:
            continue
        current_groups.append(group)
    return current_groups


def has_current_admin_access(
    bot: TeleBot,
    user_id: int,
    admins: AdminsDB | None = None,
) -> bool:
    return bool(get_current_admin_clans(bot, user_id, admins))


def get_active_admin_group(
    bot: TeleBot,
    user_id: int,
    admins: AdminsDB | None = None,
) -> AccessGroup:
    database = admins or get_admins_db()
    group = database.get_active_group(user_id)
    if group is None:
        raise ValueError("Для администратора не выбран клан")
    require_admin_access(bot, user_id, group.group_id, database)
    return group
