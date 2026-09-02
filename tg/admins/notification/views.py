from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from logger.app_logger import logger
from tg.admins.common import get_active_admin_group
from tg.utils import Button, get_ids, get_username


def notifications_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    get_active_admin_group(bot, user_id)
    logger.debug(
        "Opening notifications menu for admin_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button(
            "🔔 Обновить данные", "admins/notifications/standard"
        ).inline(),
        Button("✍️ Свой текст", "admins/notifications/custom").inline(),
    )
    keyboard.row(Button("⬅️ Назад в админ-панель", "admins").inline())
    bot.edit_message_text(
        "Уведомления пользователям",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )
