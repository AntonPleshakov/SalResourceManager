from telebot import TeleBot

from tg import admins
from tg import group_registration
from tg import user_data
from tg.navigation import home
from tg.utils import empty_filter


def register_handlers(bot: TeleBot):
    group_registration.register_handlers(bot)
    user_data.register_handlers(bot)
    bot.register_message_handler(
        home,
        content_types=["text"],
        chat_types=["private"],
        state=None,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        home, func=empty_filter, button="home", is_private=True, pass_bot=True
    )
    admins.register_handlers(bot)
