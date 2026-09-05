from db.access_group import AccessGroup
from tg.handlers import AdminContext, ClanAdminContext
from tg.utils import get_ids, get_username


def admin_context(update, bot, *groups: AccessGroup) -> AdminContext:
    user_id, chat_id, message_id = get_ids(update)
    return AdminContext(
        update=update,
        bot=bot,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        username=get_username(update),
        clans=tuple(groups),
    )


def clan_admin_context(
    update,
    bot,
    group_id: int = -100123,
    title: str = "Test clan",
) -> ClanAdminContext:
    user_id, chat_id, message_id = get_ids(update)
    return ClanAdminContext(
        update=update,
        bot=bot,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        username=get_username(update),
        group=AccessGroup(group_id, title),
    )
