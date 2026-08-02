import re

from telebot import TeleBot
from telebot.custom_filters import SimpleCustomFilter, AdvancedCustomFilter, StateFilter
from telebot.types import CallbackQuery

from db.admins import get_admins_db
from logger.app_logger import logger


class IsAdminFilter(SimpleCustomFilter):
    key = "is_admin"

    def check(self, message):
        return get_admins_db().is_admin(message.from_user.id)


class IsCallbackQueryPrivateChatFilter(SimpleCustomFilter):
    key = "is_private"

    def check(self, callback_query: CallbackQuery):
        return callback_query.message.chat.type == "private"


class PressedButtonFilter(AdvancedCustomFilter):
    key = "button"

    def check(self, callback_query: CallbackQuery, value: str):
        value = re.sub(r"([/])", r"\/", value)
        return re.fullmatch(value, callback_query.data) is not None


def add_custom_filters(bot: TeleBot):
    logger.debug("Registering custom Telegram filters")
    bot.add_custom_filter(IsAdminFilter())
    bot.add_custom_filter(IsCallbackQueryPrivateChatFilter())
    bot.add_custom_filter(PressedButtonFilter())
    bot.add_custom_filter(StateFilter(bot))
    logger.info("Custom Telegram filters registered")
