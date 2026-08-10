from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.admins import get_admins_db
from logger.app_logger import logger
from tg.admins import add_admin, del_admin, game_data, notifications, resource_status
from tg.utils import Button, empty_filter, get_ids, get_user_link, get_username


def admins_main_menu(callback_query: CallbackQuery, bot: TeleBot):
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening admin menu for user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Добавить администраторов", "admins/add_admins").inline())
    keyboard.add(Button("Удалить администратора", "admins/del_admin").inline())
    keyboard.add(Button("Список администраторов", "admins/admins_list").inline())
    keyboard.add(Button("Игровые данные", "admins/game_data").inline())
    keyboard.add(
        Button(
            "Давно не обновляли данные", "admins/stale_resources"
        ).inline()
    )
    keyboard.add(Button("Уведомления", "admins/notifications").inline())
    keyboard.add(Button("Назад в меню", "home").inline())
    bot.edit_message_text("Управление администраторами", chat_id, message_id, reply_markup=keyboard)


def admins_list(callback_query: CallbackQuery, bot: TeleBot):
    admins = get_admins_db().get_admins()
    logger.debug(
        "Showing admin list to user_id=%s username=%s count=%d",
        callback_query.from_user.id,
        get_username(callback_query),
        len(admins),
    )
    text = "Список администраторов:\n" + "\n".join(
        get_user_link(admin.user_id.value, admin.username.value) for admin in admins
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад к администраторам", "admins").inline())
    _, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)


def register_handlers(bot: TeleBot):
    logger.debug("Registering admin handlers")
    bot.register_callback_query_handler(
        admins_main_menu,
        func=empty_filter,
        button="admins",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        admins_list,
        func=empty_filter,
        button="admins/admins_list",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    add_admin.register_handlers(bot)
    del_admin.register_handlers(bot)
    game_data.register_handlers(bot)
    notifications.register_handlers(bot)
    resource_status.register_handlers(bot)
    logger.info("Admin handlers registered")
