from typing import Union

import telebot.apihelper
from telebot import ExceptionHandler, TeleBot
from telebot.handler_backends import BaseMiddleware
from telebot.types import CallbackQuery, Message

import tg.manager
from config.config import getconf, getconf_int
from db.access_group import initialize_access_group_db
from db.admins import initialize_admins_db
from db.retry import run_with_backoff
from db.user_data import initialize_user_data_db
from db.war_stages import initialize_war_stages_db
from logger.app_logger import logger
from tg.access import GroupAccessMiddleware
from tg.filters import add_custom_filters
from tg.reminders import ReminderScheduler
from tg.utils import empty_filter, get_ids, get_permissions_denied_message, get_username


bot = TeleBot(
    getconf("TOKEN"), parse_mode="HTML", use_class_middlewares=True, threaded=False
)

STARTUP_RETRY_TIMEOUT_SECONDS = 60


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
    user_id, chat_id, _ = get_ids(message)
    logger.info(
        "Permission denied for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    text = get_permissions_denied_message(user_id)
    if isinstance(message, Message):
        bot.reply_to(message, text)
    else:
        bot.send_message(chat_id, text)


def initialize_databases():
    logger.info("Initializing application databases")
    admins_db = initialize_admins_db()
    access_group_db = initialize_access_group_db()
    user_data_db = initialize_user_data_db()
    war_stages_db = initialize_war_stages_db()
    logger.info(
        "Application databases initialized: admins=%d users=%d war_days=%d access_group=%s",
        len(admins_db.get_admins()),
        len(user_data_db.get_users()),
        len(war_stages_db.get_stages()),
        "configured" if access_group_db.get_group_id() is not None else "missing",
    )
    return access_group_db


if __name__ == "__main__":
    logger.info("Starting Sal Resources Manager")
    try:
        access_group_db = run_with_backoff(
            initialize_databases,
            timeout_seconds=STARTUP_RETRY_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception(
            "Startup initialization failed; Sal Resources Manager is exiting"
        )
        raise

    logger.debug("Registering Telegram filters, middleware and handlers")
    add_custom_filters(bot)
    bot.setup_middleware(GroupAccessMiddleware(bot, access_group_db))
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
    reminder_scheduler = ReminderScheduler(bot, getconf_int("REMINDER_HOUR", 13))
    reminder_scheduler.start()
    logger.info("Sal Resources Manager started")
    try:
        bot.infinity_polling()
    finally:
        logger.info("Stopping Sal Resources Manager")
        reminder_scheduler.stop()
        logger.info("Sal Resources Manager stopped")
