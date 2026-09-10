from typing import Union

import telebot.apihelper
from telebot import ExceptionHandler, TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import tg.manager
from config.config import getconf, is_debug_mode
from db.initializer import initialize_database
from logger.app_logger import logger
from tg.access import GroupAccessMiddleware
from tg.clans import register_membership_handlers, sync_migrated_clan_titles
from tg.debug_bot import DebugTeleBot
from tg.filters import add_custom_filters
from tg.handlers import HandlerRegistry
from tg.metrics import (
    APPLICATION_METRICS,
    METRICS_LISTEN,
    METRICS_PORT,
    instrument_registered_handlers,
    register_player_account_metrics,
    start_metrics_server,
    TelegramMetricsMiddleware,
)
from tg.middleware import NoOpPostProcessMiddleware, NoOpPreProcessMiddleware
from tg.polling import serve_polling
from tg.reminders import ReminderScheduler
from tg.scheduling import AdminReconciliationScheduler
from tg.utils import (
    Button,
    get_ids,
    get_permissions_denied_message,
    get_username,
)
from tg.webhook import load_webhook_settings, serve_webhook


bot_class = DebugTeleBot if is_debug_mode() else TeleBot
bot = bot_class(
    getconf("TOKEN"),
    parse_mode="HTML",
    use_class_middlewares=True,
    threaded=True,
    num_threads=1,
)


class AlwaysAnswerCallbackQueryMiddleware(NoOpPostProcessMiddleware):
    def __init__(self, telegram_bot: TeleBot):
        super().__init__()
        self.update_types = ["callback_query"]
        self._bot = telegram_bot

    def pre_process(self, message: CallbackQuery, _: dict) -> None:
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

class UserFacingErrorMiddleware(NoOpPreProcessMiddleware):
    def __init__(self, telegram_bot: TeleBot):
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._bot = telegram_bot

    def post_process(
        self,
        update: Union[Message, CallbackQuery],
        _: dict,
        exception: BaseException | None,
    ) -> None:
        if exception is None:
            return

        user_id, chat_id = get_ids(update)[:2]
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


def permission_denied_message(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> None:
    user_id, chat_id = get_ids(message)[:2]
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
        lambda: databases.user_data.get_account_counts().values(),
        clan_account_counts=databases.user_data.get_clan_account_counts,
    )
    logger.info(
        "Application databases initialized: admins=%d users=%d "
        "release_views=%d clans=%d",
        databases.admins.get_admin_count(),
        len(databases.user_data.get_users()),
        databases.release_views.get_users_count(),
        len(databases.access_group.get_groups()),
    )
    return databases


if __name__ == "__main__":
    logger.info("Starting Sal Resources Manager")
    debug_mode = is_debug_mode()
    try:
        webhook_settings = None if debug_mode else load_webhook_settings()
        databases = initialize_databases()
        if isinstance(bot, DebugTeleBot):
            bot.configure_fake_clan_data(
                databases.access_group,
                databases.admins,
            )
        sync_migrated_clan_titles(bot, databases.access_group)
    except Exception:
        logger.exception(
            "Startup initialization failed; Sal Resources Manager is exiting"
        )
        raise

    logger.debug("Registering Telegram filters, middleware and handlers")
    add_custom_filters(bot)
    bot.setup_middleware(
        GroupAccessMiddleware(
            bot, databases.access_group, user_data_db=databases.user_data
        )
    )
    bot.setup_middleware(TelegramMetricsMiddleware())
    register_membership_handlers(
        bot,
        databases.access_group,
        databases.user_data,
    )
    tg.manager.register_handlers(bot)
    tg.manager.configure_commands(bot)
    handlers = HandlerRegistry(bot)
    handlers.private_message(
        permission_denied_message,
        admin=False,
    )
    handlers.private_callback(
        permission_denied_message,
        admin=False,
    )
    instrument_registered_handlers(bot)
    bot.setup_middleware(AlwaysAnswerCallbackQueryMiddleware(bot))
    bot.setup_middleware(UserFacingErrorMiddleware(bot))
    bot.exception_handler = BotExceptionHandler()
    reminder_scheduler = ReminderScheduler(bot)
    admin_reconciliation_scheduler = AdminReconciliationScheduler(bot)
    metrics_server = start_metrics_server()
    try:
        reminder_scheduler.start()
        admin_reconciliation_scheduler.start()
        APPLICATION_METRICS.ready.set(1)
        if debug_mode:
            logger.info(
                "Sal Resources Manager started; polling Telegram and "
                "exposing metrics on %s:%d/metrics",
                METRICS_LISTEN,
                METRICS_PORT,
            )
            serve_polling(bot)
        else:
            logger.info(
                "Sal Resources Manager started; listening for Telegram "
                "webhooks on %s:%d/%s/ and exposing metrics on "
                "%s:%d/metrics",
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
            admin_reconciliation_scheduler.stop()
            reminder_scheduler.stop()
            bot.stop_bot()
        finally:
            metrics_server.stop()
        logger.info("Sal Resources Manager stopped")
