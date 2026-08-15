from typing import Union

import telebot.apihelper
from telebot import ExceptionHandler, TeleBot
from telebot.handler_backends import BaseMiddleware
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import tg.manager
from config.config import getconf
from db.initializer import initialize_database
from logger.app_logger import logger
from tg.access import GroupAccessMiddleware
from tg.filters import add_custom_filters
from tg.metrics import (
    APPLICATION_METRICS,
    METRICS_LISTEN,
    METRICS_PORT,
    register_player_account_metrics,
    start_metrics_server,
    TelegramMetricsMiddleware,
)
from tg.reminders import ReminderScheduler
from tg.utils import (
    Button,
    empty_filter,
    get_ids,
    get_permissions_denied_message,
    get_username,
)
from tg.webhook import load_webhook_settings, serve_webhook


bot = TeleBot(
    getconf("TOKEN"),
    parse_mode="HTML",
    use_class_middlewares=True,
    threaded=True,
    num_threads=1,
)


class AlwaysAnswerCallbackQueryMiddleware(BaseMiddleware):
    def __init__(self, telegram_bot: TeleBot):
        super().__init__()
        self.update_types = ["callback_query"]
        self._bot = telegram_bot

    def pre_process(self, message: CallbackQuery, data: dict) -> None:
        logger.debug(
            "Processing callback query for user_id=%s username=%s",
            message.from_user.id,
            get_username(message),
        )
        try:
            self._bot.answer_callback_query(message.id)
        except telebot.apihelper.ApiTelegramException as error:
            logger.info("Unable to answer callback query: %s", error)
        return None

    def post_process(
        self, message: CallbackQuery, data: dict, exception: BaseException | None
    ) -> None:
        pass


class UserFacingErrorMiddleware(BaseMiddleware):
    def __init__(self, telegram_bot: TeleBot):
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._bot = telegram_bot

    def pre_process(
        self, update: Union[Message, CallbackQuery], data: dict
    ) -> None:
        return None

    def post_process(
        self,
        update: Union[Message, CallbackQuery],
        data: dict,
        exception: BaseException | None,
    ) -> None:
        if exception is None:
            return

        user_id, chat_id, _ = get_ids(update)
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(Button("Вернуться в меню", "home").inline())
        try:
            self._bot.send_message(
                chat_id,
                "Не удалось выполнить действие из-за неожиданной ошибки. "
                "Вернитесь в меню и попробуйте снова.",
                reply_markup=keyboard,
            )
        except Exception as notification_error:
            logger.warning(
                "Unable to notify user_id=%s about Telegram processing error: %s",
                user_id,
                notification_error,
            )


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
    databases = initialize_database()
    register_player_account_metrics(
        lambda: databases.user_data.get_account_counts().values()
    )
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
    bot.setup_middleware(TelegramMetricsMiddleware())
    tg.manager.register_handlers(bot)
    tg.manager.configure_commands(bot)
    bot.register_message_handler(
        permission_denied_message, chat_types=["private"], is_admin=False
    )
    bot.register_callback_query_handler(
        permission_denied_message,
        func=empty_filter,
        is_private=True,
        is_admin=False,
    )
    bot.setup_middleware(AlwaysAnswerCallbackQueryMiddleware(bot))
    bot.setup_middleware(UserFacingErrorMiddleware(bot))
    bot.exception_handler = BotExceptionHandler()
    reminder_scheduler = ReminderScheduler(bot)
    metrics_server = start_metrics_server()
    try:
        reminder_scheduler.start()
        APPLICATION_METRICS.ready.set(1)
        logger.info(
            "Sal Resources Manager started; listening for Telegram webhooks "
            "on %s:%d/%s/ and exposing metrics on %s:%d/metrics",
            webhook_settings.listen,
            webhook_settings.port,
            webhook_settings.url_path,
            METRICS_LISTEN,
            METRICS_PORT,
        )
        serve_webhook(bot, webhook_settings)
    finally:
        APPLICATION_METRICS.ready.set(0)
        logger.info("Stopping Sal Resources Manager")
        try:
            reminder_scheduler.stop()
            bot.stop_bot()
        finally:
            metrics_server.stop()
        logger.info("Sal Resources Manager stopped")
