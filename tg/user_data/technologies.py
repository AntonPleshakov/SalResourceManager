from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from resources.user_data import TECHNOLOGY_FIELDS
from tg.user_data.common import section_menu
from tg.utils import empty_filter


def technologies_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    section_menu(
        message, bot, "Технологии", "technologies", TECHNOLOGY_FIELDS, notice
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        technologies_menu,
        func=empty_filter,
        button="technologies",
        is_private=True,
        pass_bot=True,
    )
