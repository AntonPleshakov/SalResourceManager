from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

import tg.user_data as user_data


DESTINATIONS = {"resources", "technologies", "pets", "war_calculator"}


def requested_destination(message: Union[Message, CallbackQuery]) -> str:
    if not isinstance(message, CallbackQuery):
        return "accounts"
    candidate = message.data.split("/")[-1]
    return candidate if candidate in DESTINATIONS else "accounts"


def open_destination(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    destination: str,
    notice: str = "",
) -> None:
    if destination == "resources":
        user_data.resources_menu(message, bot, notice)
    elif destination == "technologies":
        user_data.technologies_menu(message, bot, notice)
    elif destination == "pets":
        user_data.pets_menu(message, bot, notice)
    elif destination == "war_calculator":
        from tg.war.personal import personal_war_points

        personal_war_points(message, bot)
    else:
        from tg.user_data.account.menu import accounts_menu

        accounts_menu(message, bot, notice)
