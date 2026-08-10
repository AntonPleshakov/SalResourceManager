from typing import Union

import telebot.apihelper
from telebot import ExceptionHandler, TeleBot
from telebot.handler_backends import BaseMiddleware
from telebot.types import CallbackQuery, Message

import tg.manager
from config.config import getconf, getconf_int
from db.sqlite.initializer import initialize_sqlite_databases
from logger.app_logger import logger
from tg.access import GroupAccessMiddleware
from tg.filters import add_custom_filters
from tg.reminders import ReminderScheduler
from tg.utils import empty_filter, get_ids, get_permissions_denied_message, get_username
from tg.webhook import load_webhook_settings, serve_webhook


bot = TeleBot(
    getconf("TOKEN"),
    parse_mode="HTML",
    use_class_middlewares=True,
    threaded=True,
    num_threads=1,
)


class AlwaysAnswerCallbackQueryMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.update_types = ["callback_query"]

    def pre_process(self, message: CallbackQuery, data: dict) -> None:
        logger.debug(
            "Processing callback query for user_id=%s username=%s",
            message.from_user.id,
            get_username(message),
        )
        return None

    def post_process(
        self, message: CallbackQuery, data: dict, exception: BaseException | None
    ):
        try:
            bot.answer_callback_query(message.id)
        except telebot.apihelper.ApiTelegramException as error:
            logger.info("Unable to answer callback query: %s", error)


class BotExceptionHandler(ExceptionHandler):
    def handle(self, exception: BaseException):
        logger.exception("Telegram update processing exception: %s", exception)
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
    databases = initialize_sqlite_databases()
    logger.info(
        "Application databases initialized: admins=%d users=%d "
        "release_views=%d access_group=%s",
        len(databases.admins.get_admins()),
        len(databases.user_data.get_users()),
        databases.release_views.get_users_count(),
        "configured"
        if databases.access_group.get_group_id() is not None
        else "missing",
    )
    return databases.access_group


if __name__ == "__main__":
    logger.info("Starting Sal Resources Manager")
    try:
        webhook_settings = load_webhook_settings()
        access_group_db = initialize_databases()
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
    logger.info(
        "Sal Resources Manager started; listening for Telegram webhooks "
        "on %s:%d/%s/",
        webhook_settings.listen,
        webhook_settings.port,
        webhook_settings.url_path,
    )
    try:
        serve_webhook(bot, webhook_settings)
    finally:
        logger.info("Stopping Sal Resources Manager")
        reminder_scheduler.stop()
        bot.stop_bot()
        logger.info("Sal Resources Manager stopped")
