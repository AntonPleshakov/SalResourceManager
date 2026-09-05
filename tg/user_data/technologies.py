from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from resources.user_data import TECHNOLOGY_FIELDS, UserData
from tg.user_data.common import (
    MenuContent,
    build_section_menu,
    show_section_menu,
)
from tg.handlers import HandlerRegistry


def build_technologies_menu(
    user: UserData, notice: str = ""
) -> MenuContent:
    return build_section_menu(
        user,
        "Технологии",
        "technologies",
        TECHNOLOGY_FIELDS,
        notice,
    )


def technologies_menu(
    update: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    show_section_menu(
        update,
        bot,
        "Технологии",
        "technologies",
        TECHNOLOGY_FIELDS,
        notice,
    )


def register_handlers(bot: TeleBot) -> None:
    HandlerRegistry(bot).private_callback(
        technologies_menu,
        button="technologies",
    )
