from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.admins.common import (
    AdminAccessError,
    get_current_admin_clans,
    require_admin_access,
)
from tg.utils import Button, empty_filter, get_ids


def clans_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    groups = get_current_admin_clans(bot, user_id, get_admins_db())
    keyboard = InlineKeyboardMarkup(row_width=1)
    for group in groups:
        keyboard.add(
            Button(group.title, f"admins/clans/{group.group_id}").inline()
        )
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    bot.edit_message_text(
        "<b>Управляемый клан</b>\n\n"
        "Выберите клан для административных действий.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def select_clan(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = callback_query.from_user.id
    try:
        group_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
        admins = get_admins_db()
        require_admin_access(bot, user_id, group_id, admins)
        admins.select_group(user_id, group_id)
    except (AdminAccessError, ValueError) as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return

    from tg.admins import admins_main_menu

    admins_main_menu(callback_query, bot)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering admin clan-selection handlers")
    bot.register_callback_query_handler(
        clans_menu,
        func=empty_filter,
        button="admins/clans",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        select_clan,
        func=empty_filter,
        button=r"admins/clans/-?[0-9]+",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
