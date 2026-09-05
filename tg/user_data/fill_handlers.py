from telebot import TeleBot

from tg.handlers import HandlerRegistry
from tg.user_data.editing_common import EditUserDataStates


def register_handlers(bot: TeleBot) -> None:
    from tg.user_data.fill import (
        fill_section,
        fill_tracked_fields,
        save_fill_value,
        skip_fill_value,
    )

    handlers = HandlerRegistry(bot)
    handlers.private_callback(
        fill_section,
        button=r"user_data/fill/(resources|technologies)",
    )
    handlers.private_callback(
        fill_tracked_fields,
        button=r"user_data/fill/tracked/[0-9,]+",
    )
    handlers.private_callback(
        skip_fill_value,
        button="user_data/fill/skip",
        state=EditUserDataStates.fill_values,
    )
    handlers.private_message(
        save_fill_value,
        content_types=["text"],
        state=EditUserDataStates.fill_values,
    )
