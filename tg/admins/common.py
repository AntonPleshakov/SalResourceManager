from db.access_group import AccessGroup
from db.admins import AdminsDB
from db.initializer import get_admins_db


class AdminAccessError(ValueError):
    pass


def require_admin_access(
    user_id: int,
    group_id: int,
    admins: AdminsDB | None = None,
) -> None:
    database = admins or get_admins_db()
    if not database.is_clan_admin(user_id, group_id):
        raise AdminAccessError("Нет прав администратора выбранного клана")


def get_active_admin_group(
    user_id: int, admins: AdminsDB | None = None
) -> AccessGroup:
    database = admins or get_admins_db()
    group = database.get_active_group(user_id)
    if group is None:
        raise ValueError("Для администратора не выбран клан")
    require_admin_access(user_id, group.group_id, database)
    return group
