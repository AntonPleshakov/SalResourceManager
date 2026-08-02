from telebot import TeleBot
from telebot.types import Message

from db.access_group import get_access_group_db
from db.admins import get_admins_db
from logger.app_logger import logger
from tg.utils import get_username


NOT_ADMIN_MESSAGE = "Только администратор бота может зарегистрировать группу."
BOT_NOT_ADMIN_MESSAGE = (
    "Сначала назначьте бота администратором этой группы, затем повторите команду."
)
REGISTRATION_FAILED_MESSAGE = (
    "Не удалось зарегистрировать группу. Попробуйте ещё раз позже."
)
REGISTRATION_SUCCESS_MESSAGE = "Группа зарегистрирована. Доступ участникам открыт."


def register_access_group(message: Message, bot: TeleBot) -> None:
    logger.info(
        "Access group registration requested by user_id=%s username=%s chat_id=%s",
        message.from_user.id,
        get_username(message),
        message.chat.id,
    )
    if not get_admins_db().is_admin(message.from_user.id):
        logger.warning(
            "Access group registration rejected for non-admin user_id=%s username=%s",
            message.from_user.id,
            get_username(message),
        )
        bot.reply_to(message, NOT_ADMIN_MESSAGE)
        return

    try:
        bot_user = bot.get_me()
        bot_member = bot.get_chat_member(message.chat.id, bot_user.id)
        if bot_member.status not in {"creator", "administrator"}:
            logger.warning(
                "Access group registration rejected: bot is not admin in chat_id=%s",
                message.chat.id,
            )
            bot.reply_to(message, BOT_NOT_ADMIN_MESSAGE)
            return
        get_access_group_db().set_group_id(message.chat.id)
    except Exception as error:
        logger.exception("Unable to register access group: %s", error)
        bot.reply_to(message, REGISTRATION_FAILED_MESSAGE)
        return

    logger.info(
        "Access group chat_id=%s registered by user_id=%s username=%s",
        message.chat.id,
        message.from_user.id,
        get_username(message),
    )
    bot.reply_to(message, REGISTRATION_SUCCESS_MESSAGE)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering access group handler")
    bot.register_message_handler(
        register_access_group,
        commands=["register_group"],
        chat_types=["group", "supergroup"],
        pass_bot=True,
    )
