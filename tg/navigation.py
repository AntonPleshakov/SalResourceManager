from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.admins import get_admins_db
from logger.app_logger import logger
from tg.releases import show_unseen_releases
from tg.utils import Button, get_ids, get_username


def home(message: Union[Message, CallbackQuery], bot: TeleBot):
    user_id, chat_id, message_id = get_ids(message)
    bot.delete_state(user_id)
    if show_unseen_releases(message, bot):
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Ресурсы", "resources").inline())
    keyboard.add(Button("Технологии", "technologies").inline())
    keyboard.add(Button("Очки войны", "war_menu").inline())
    keyboard.add(Button("Что нового", "releases").inline())
    logger.debug(
        "Opening home menu for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    if get_admins_db().is_admin(user_id):
        keyboard.add(Button("Администраторы", "admins").inline())
    text = "Выберите раздел"
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
