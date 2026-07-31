from typing import Union

import telebot.apihelper
from telebot import ExceptionHandler, TeleBot
from telebot.handler_backends import BaseMiddleware
from telebot.types import CallbackQuery, Message

import tg.manager
from config.config import getconf
from db.admins import initialize_admins_db
from db.user_data import initialize_user_data_db
from db.war_stages import initialize_war_stages_db
from logger.app_logger import logger
from tg.filters import add_custom_filters
from tg.utils import empty_filter, get_ids, get_permissions_denied_message, get_username


bot = TeleBot(
    getconf("TOKEN"), parse_mode="HTML", use_class_middlewares=True, threaded=False
)


class AlwaysAnswerCallbackQueryMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.update_types = ["callback_query"]

    def post_process(
        self, message: CallbackQuery, data: dict, exception: BaseException | None
    ):
        try:
            bot.answer_callback_query(message.id)
        except telebot.apihelper.ApiTelegramException as error:
            logger.info("Unable to answer callback query: %s", error)


class BotExceptionHandler(ExceptionHandler):
    def handle(self, exception: BaseException):
        logger.exception("Polling exception: %s", exception)
        return True


def permission_denied_message(message: Union[Message, CallbackQuery]):
    logger.info("Permission denied for user '%s'", get_username(message))
    user_id, chat_id, _ = get_ids(message)
    text = get_permissions_denied_message(user_id)
    if isinstance(message, Message):
        bot.reply_to(message, text)
    else:
        bot.send_message(chat_id, text)


if __name__ == "__main__":
    logger.info("Sal Resources Manager started")
    initialize_admins_db()
    initialize_user_data_db()
    initialize_war_stages_db()
    add_custom_filters(bot)
    tg.manager.register_handlers(bot)
    bot.register_message_handler(
        permission_denied_message, chat_types=["private"], is_admin=False
    )
    bot.register_callback_query_handler(
        permission_denied_message,
        func=empty_filter,
        is_private=True,
        is_admin=False,
    )
    bot.setup_middleware(AlwaysAnswerCallbackQueryMiddleware())
    bot.exception_handler = BotExceptionHandler()
    bot.infinity_polling()
