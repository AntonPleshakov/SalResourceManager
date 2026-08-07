from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.admins import get_admins_db
from logger.app_logger import logger
from tg.navigation import home
from tg.utils import Button, empty_filter, get_ids, get_user_link, get_username


class DelAdminStates(StatesGroup):
    admin_id = State()
    confirmed = State()


def del_admin_options(callback_query: CallbackQuery, bot: TeleBot):
    requester_id = callback_query.from_user.id
    current_admins = [
        admin
        for admin in get_admins_db().get_admins()
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
        keyboard.add(Button(admin.username.value, str(admin.user_id.value)).inline())
    keyboard.add(Button("Назад к администраторам", "admins").inline())
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        "Выберите пользователя, которого нужно лишить прав администратора.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )
    bot.set_state(user_id, DelAdminStates.admin_id)


def del_admin_confirmation(callback_query: CallbackQuery, bot: TeleBot):
    admin = get_admins_db().get_admin(int(callback_query.data))
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
    keyboard.row(Button("Да", f"approved/{admin.user_id.value}").inline())
    keyboard.row(Button("Нет", "admins").inline())
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
    admin = get_admins_db().get_admin(admin_id)
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
    get_admins_db().del_admin(admin_id)
    user_id, _, _ = get_ids(callback_query)
    bot.delete_state(user_id)
    bot.answer_callback_query(callback_query.id, "Права администратора отозваны")
    try:
        bot.send_message(admin_id, "Ваши права администратора были отозваны.")
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
