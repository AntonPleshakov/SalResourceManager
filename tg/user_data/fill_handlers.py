from telebot import TeleBot

from tg.user_data.editing_common import (
    EditUserDataStates,
    PRIVATE_CALLBACK_HANDLER,
    PRIVATE_TEXT_HANDLER,
)


def register_handlers(bot: TeleBot) -> None:
    from tg.user_data.fill import (
        fill_section,
        fill_tracked_fields,
        save_fill_value,
        skip_fill_value,
    )

    bot.register_callback_query_handler(
        fill_section,
        button=r"user_data/fill/(resources|technologies)",
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_callback_query_handler(
        fill_tracked_fields,
        button=r"user_data/fill/tracked/[0-9,]+",
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_callback_query_handler(
        skip_fill_value,
        button="user_data/fill/skip",
        state=EditUserDataStates.fill_values,
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_message_handler(
        save_fill_value,
        state=EditUserDataStates.fill_values,
        **PRIVATE_TEXT_HANDLER,
    )
