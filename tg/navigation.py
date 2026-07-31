from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.admins import get_admins_db
from db.user_data import get_user_data_db
from tg.utils import Button, get_ids


def home(message: Union[Message, CallbackQuery], bot: TeleBot):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Ресурсы", "resources").inline())
    keyboard.add(Button("Технологии", "technologies").inline())
    keyboard.add(Button("Война", "war").inline())
    keyboard.add(InlineKeyboardButton("Игровые данные", url=get_user_data_db().get_url()))
    user_id, chat_id, message_id = get_ids(message)
    if get_admins_db().is_admin(user_id):
        keyboard.add(Button("Администраторы", "admins").inline())
    text = "Выберите раздел"
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
    bot.delete_state(user_id)
