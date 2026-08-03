from telebot import TeleBot

from tg import admins
from tg import group_registration
from tg import releases
from tg import user_data
from tg import war
from tg.navigation import home
from tg.utils import empty_filter
from logger.app_logger import logger


def register_handlers(bot: TeleBot):
    logger.debug("Registering Telegram command and callback handlers")
    group_registration.register_handlers(bot)
    user_data.register_handlers(bot)
    war.register_handlers(bot)
    releases.register_handlers(bot)
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
    logger.info("Telegram handlers registered")
