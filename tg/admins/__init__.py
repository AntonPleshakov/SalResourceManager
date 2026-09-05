from collections.abc import Sequence

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.access_group import AccessGroup
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
from tg.handlers import (
    ActiveClan,
    AdminContext,
    ClanAdminContext,
    HandlerRegistry,
)
from tg.utils import Button, get_ids, get_user_link, get_username


def _show_admins_main_menu(
    callback_query: CallbackQuery,
    bot: TeleBot,
    groups: Sequence[AccessGroup],
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening admin menu for user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    keyboard = InlineKeyboardMarkup()
    admins = get_admins_db()
    active_group = admins.get_active_group(user_id)
    group = next(
        (
            candidate
            for candidate in groups
            if active_group is not None
            and candidate.group_id == active_group.group_id
        ),
        None,
    )
    if group is None:
        if groups:
            keyboard.row(
                Button("🏰 Выбрать клан", "admins/clans").inline()
            )
            keyboard.row(
                Button("➕ Добавить клан", "admins/register_group").inline()
            )
        keyboard.row(Button("⬅️ Назад в меню", "home").inline())
        bot.edit_message_text(
            "<b>Админ-панель</b>\n\n"
            + (
                "Выберите клан для административных действий."
                if groups
                else "У вас нет актуальных прав администратора клана."
            ),
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
    if len(groups) > 1:
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


def admins_main_menu(context: AdminContext) -> None:
    _show_admins_main_menu(
        context.update,
        context.bot,
        list(context.clans),
    )


def admins_list(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id = callback_query.from_user.id
    admins_db = get_admins_db()
    admins = admins_db.get_clan_admins(context.group.group_id)
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
    handlers = HandlerRegistry(bot)
    handlers.admin_callback(
        admins_main_menu,
        button="admins",
    )
    handlers.clan_admin_callback(
        admins_list,
        button="admins/admins_list",
        clan=ActiveClan(),
    )
    add_admin.register_handlers(bot)
    clans.register_handlers(bot)
    del_admin.register_handlers(bot)
    game_data.register_handlers(bot)
    notifications.register_handlers(bot)
    rename_clan.register_handlers(bot)
    resource_status.register_handlers(bot)
    logger.info("Admin handlers registered")
