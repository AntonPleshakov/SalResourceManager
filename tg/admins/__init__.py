from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.admins import (
    add_admin,
    clans,
    del_admin,
    game_data,
    notifications,
    rename_clan,
    resource_status,
)
from tg.utils import Button, empty_filter, get_ids, get_user_link, get_username


def admins_main_menu(callback_query: CallbackQuery, bot: TeleBot):
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening admin menu for user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    keyboard = InlineKeyboardMarkup()
    admins = get_admins_db()
    group = admins.get_active_group(user_id)
    if group is None:
        keyboard.row(
            Button("➕ Добавить клан", "admins/register_group").inline()
        )
        keyboard.row(Button("⬅️ Назад в меню", "home").inline())
        bot.edit_message_text(
            "<b>Админ-панель</b>\n\n"
            "Сначала зарегистрируйте группу клана.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    keyboard.row(Button("👥 Список игроков", "admins/last_updates").inline())
    keyboard.row(Button("📣 Уведомления", "admins/notifications").inline())
    keyboard.row(Button("📊 Игровые данные", "admins/game_data").inline())
    keyboard.row(
        Button("➕ Добавить клан", "admins/register_group").inline()
    )
    if len(admins.get_clans(user_id)) > 1:
        keyboard.row(Button("🔄 Сменить клан", "admins/clans").inline())
    keyboard.row(
        Button("✏️ Переименовать клан", "admins/rename_clan").inline()
    )
    keyboard.row(Button("👥 Список администраторов", "admins/admins_list").inline())
    keyboard.row(Button("➕ Добавить администраторов", "admins/add_admins").inline())
    keyboard.row(Button("🗑 Удалить администратора", "admins/del_admin").inline())
    keyboard.row(Button("⬅️ Назад в меню", "home").inline())
    bot.edit_message_text(
        "<b>Админ-панель</b>\n"
        f"Клан: <b>{formatting.escape_html(group.title)}</b>\n\n"
        "Выберите действие.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def admins_list(callback_query: CallbackQuery, bot: TeleBot):
    user_id = callback_query.from_user.id
    admins_db = get_admins_db()
    group = admins_db.get_active_group(user_id)
    admins = [] if group is None else admins_db.get_admins(group.group_id)
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
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    chat_id, message_id = get_ids(callback_query)[1:]
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
    clans.register_handlers(bot)
    del_admin.register_handlers(bot)
    game_data.register_handlers(bot)
    notifications.register_handlers(bot)
    rename_clan.register_handlers(bot)
    resource_status.register_handlers(bot)
    logger.info("Admin handlers registered")
