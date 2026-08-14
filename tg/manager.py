from telebot import TeleBot
from telebot.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    Message,
    ReplyKeyboardRemove,
)

from tg import admins
from tg import group_registration
from tg import releases
from tg import user_data
from tg import war
from tg.navigation import home, start, toggle_reminders
from tg.utils import empty_filter
from logger.app_logger import logger


VISIBLE_COMMANDS = (
    BotCommand("start", "Открыть бота"),
    BotCommand("menu", "Открыть главное меню"),
)


def _has_active_state(message: Message, bot: TeleBot) -> bool:
    return bot.get_state(message.from_user.id, message.chat.id) is not None


def _notify_about_cancelled_state(message: Message, bot: TeleBot) -> None:
    if _has_active_state(message, bot):
        bot.send_message(
            message.chat.id,
            "Текущее действие отменено.",
            reply_markup=ReplyKeyboardRemove(),
        )


def start_command(message: Message, bot: TeleBot) -> None:
    _notify_about_cancelled_state(message, bot)
    start(message, bot)


def open_menu_command(message: Message, bot: TeleBot) -> None:
    _notify_about_cancelled_state(message, bot)
    home(message, bot)


def cancel_command(message: Message, bot: TeleBot) -> None:
    if not _has_active_state(message, bot):
        bot.reply_to(message, "Сейчас нет активного действия.")
        return
    bot.send_message(
        message.chat.id,
        "Текущее действие отменено.",
        reply_markup=ReplyKeyboardRemove(),
    )
    home(message, bot)


def configure_commands(bot: TeleBot) -> None:
    try:
        bot.set_my_commands(
            list(VISIBLE_COMMANDS),
            scope=BotCommandScopeAllPrivateChats(),
        )
    except Exception as error:
        logger.warning("Unable to configure Telegram commands: %s", error)


def register_handlers(bot: TeleBot):
    logger.debug("Registering Telegram command and callback handlers")
    bot.register_message_handler(
        start_command,
        commands=["start"],
        chat_types=["private"],
        pass_bot=True,
    )
    bot.register_message_handler(
        open_menu_command,
        commands=["menu"],
        chat_types=["private"],
        pass_bot=True,
    )
    bot.register_message_handler(
        cancel_command,
        commands=["cancel"],
        chat_types=["private"],
        pass_bot=True,
    )
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
    bot.register_callback_query_handler(
        toggle_reminders,
        func=empty_filter,
        button="reminders/toggle",
        is_private=True,
        pass_bot=True,
    )
    admins.register_handlers(bot)
    logger.info("Telegram handlers registered")
