from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.admins.common import (
    AdminAccessError,
    get_active_admin_group,
    require_admin_access,
)
from tg.navigation import home
from tg.utils import Button, empty_filter, get_ids, get_user_link, get_username


class DelAdminStates(StatesGroup):
    admin_id = State()
    confirmed = State()


def del_admin_options(callback_query: CallbackQuery, bot: TeleBot):
    requester_id = callback_query.from_user.id
    group = get_active_admin_group(requester_id)
    current_admins = [
        admin
        for admin in get_admins_db().get_clan_admins(group.group_id)
        if admin.user_id.value != requester_id
    ]
    logger.info(
        "Admin removal requested by user_id=%s username=%s candidates=%d",
        requester_id,
        get_username(callback_query),
        len(current_admins),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    for admin in current_admins:
        keyboard.add(
            Button(
                f"🗑 {admin.username.value}",
                str(admin.user_id.value),
            ).inline()
        )
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        "Выберите пользователя, которого нужно лишить прав администратора.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )
    bot.set_state(user_id, DelAdminStates.admin_id)
    bot.add_data(
        user_id,
        admin_group_id=group.group_id,
        admin_group_title=group.title,
    )


def del_admin_confirmation(callback_query: CallbackQuery, bot: TeleBot):
    requester_id = callback_query.from_user.id
    with bot.retrieve_data(requester_id) as data:
        group_id = data.get("admin_group_id")
    try:
        if not isinstance(group_id, int):
            raise AdminAccessError("Не выбран клан")
        require_admin_access(requester_id, group_id, get_admins_db())
    except AdminAccessError:
        bot.delete_state(requester_id)
        bot.answer_callback_query(
            callback_query.id, "Нет прав администратора выбранного клана"
        )
        home(callback_query, bot)
        return
    admin = get_admins_db().get_clan_admin(
        int(callback_query.data), group_id
    )
    if admin is None:
        logger.warning(
            "Admin removal target not found requester_id=%s username=%s target=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            callback_query.data,
        )
        bot.answer_callback_query(callback_query.id, "Администратор не найден")
        home(callback_query, bot)
        return
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button("🗑 Да", f"approved/{admin.user_id.value}").inline(),
        Button("✖️ Нет", "admins").inline(),
    )
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        f"Лишить прав {get_user_link(admin.user_id.value, admin.username.value)}?",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )
    bot.set_state(user_id, DelAdminStates.confirmed)


def del_admin_approved(callback_query: CallbackQuery, bot: TeleBot):
    admin_id = int(callback_query.data.split("/")[-1])
    requester_id = callback_query.from_user.id
    with bot.retrieve_data(requester_id) as data:
        group_id = data.get("admin_group_id")
        group_title = data.get("admin_group_title")
    try:
        if not isinstance(group_id, int):
            raise AdminAccessError("Не выбран клан")
        require_admin_access(requester_id, group_id, get_admins_db())
    except AdminAccessError:
        bot.delete_state(requester_id)
        bot.answer_callback_query(
            callback_query.id, "Нет прав администратора выбранного клана"
        )
        home(callback_query, bot)
        return
    admin = get_admins_db().get_clan_admin(admin_id, group_id)
    if admin is None:
        logger.warning(
            "Approved admin removal target not found requester_id=%s username=%s target_id=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            admin_id,
        )
        bot.answer_callback_query(callback_query.id, "Администратор не найден")
        home(callback_query, bot)
        return
    logger.info(
        "Removing admin target_id=%s target_username=%s requester_id=%s requester_username=%s",
        admin_id,
        admin.username.value,
        callback_query.from_user.id,
        get_username(callback_query),
    )
    get_admins_db().del_clan_admin(admin_id, group_id)
    user_id = get_ids(callback_query)[0]
    bot.delete_state(user_id)
    bot.answer_callback_query(
        callback_query.id, "Права администратора клана отозваны"
    )
    try:
        group_title = (
            group_title
            if isinstance(group_title, str) and group_title
            else str(group_id)
        )
        bot.send_message(
            admin_id,
            "Ваши права администратора клана "
            f"«{formatting.escape_html(group_title)}» были отозваны.",
        )
    except Exception as error:
        logger.warning(
            "Unable to notify removed admin user_id=%s username=%s: %s",
            admin_id,
            admin.username.value,
            error,
        )
    logger.info(
        "Admin removal completed target_id=%s target_username=%s",
        admin_id,
        admin.username.value,
    )
    home(callback_query, bot)


def register_handlers(bot: TeleBot):
    logger.debug("Registering delete-admin handlers")
    bot.register_callback_query_handler(
        del_admin_options,
        func=empty_filter,
        button="admins/del_admin",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        del_admin_confirmation,
        func=empty_filter,
        state=DelAdminStates.admin_id,
        button=r"\d+",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        del_admin_approved,
        func=empty_filter,
        state=DelAdminStates.confirmed,
        button=r"approved/\d+",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
