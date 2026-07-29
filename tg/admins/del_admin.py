from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.admins import admins_db
from logger.app_logger import logger
from tg.navigation import home
from tg.utils import Button, empty_filter, get_ids, get_user_link


class DelAdminStates(StatesGroup):
    admin_id = State()
    confirmed = State()


def del_admin_options(callback_query: CallbackQuery, bot: TeleBot):
    current_admins = admins_db.get_admins()[1:]
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
    admin = admins_db.get_admin(int(callback_query.data))
    if admin is None:
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
    admin = admins_db.get_admin(admin_id)
    if admin is None:
        bot.answer_callback_query(callback_query.id, "Администратор не найден")
        home(callback_query, bot)
        return
    logger.info("Removing admin %s", admin_id)
    admins_db.del_admin(admin_id)
    user_id, _, _ = get_ids(callback_query)
    bot.delete_state(user_id)
    bot.answer_callback_query(callback_query.id, "Права администратора отозваны")
    bot.send_message(admin_id, "Ваши права администратора были отозваны.")
    home(callback_query, bot)


def register_handlers(bot: TeleBot):
    bot.register_callback_query_handler(
        del_admin_options,
        func=empty_filter,
        button="admins/del_admin",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        del_admin_confirmation,
        func=empty_filter,
        state=DelAdminStates.admin_id,
        button=r"\d+",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        del_admin_approved,
        func=empty_filter,
        state=DelAdminStates.confirmed,
        button=r"approved/\d+",
        is_private=True,
        pass_bot=True,
    )
