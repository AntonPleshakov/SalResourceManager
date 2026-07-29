from typing import Tuple, Union

from telebot.types import CallbackQuery, InlineKeyboardButton, KeyboardButton, Message

from db.admins import admins_db


def get_user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def get_permissions_denied_message(user_id: int) -> str:
    admins = [
        get_user_link(admin.user_id.value, admin.username.value)
        for admin in admins_db.get_admins()
    ]
    return (
        "У вас нет прав администратора.\n"
        f"Ваш ID: {user_id}\n"
        f"Администраторы: {', '.join(admins)}"
    )


def get_ids(message: Union[Message, CallbackQuery]) -> Tuple[int, int, int]:
    user_id = message.from_user.id
    telegram_message = message.message if isinstance(message, CallbackQuery) else message
    return user_id, telegram_message.chat.id, telegram_message.id


def get_username(message: Union[Message, CallbackQuery]) -> str:
    user = message.from_user
    return user.username or user.first_name


class Button:
    def __init__(self, text: str, data: str = ""):
        self.text = text
        self.data = data

    def inline(self) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=self.text, callback_data=self.data)

    def reply(self) -> KeyboardButton:
        return KeyboardButton(text=self.text)


def empty_filter(_) -> bool:
    return True
