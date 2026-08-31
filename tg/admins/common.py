from db.access_group import AccessGroup
from db.initializer import get_admins_db


def get_active_admin_group(user_id: int) -> AccessGroup:
    group = get_admins_db().get_active_group(user_id)
    if group is None:
        raise ValueError("Для администратора не выбран клан")
    return group
