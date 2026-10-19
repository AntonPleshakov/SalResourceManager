from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from logger.app_logger import logger


def is_message_not_modified(error: BaseException) -> bool:
    return (
        isinstance(error, ApiTelegramException)
        and error.error_code == 400
        and "message is not modified" in error.description.lower()
    )


def edit_validation_message(
    bot: TeleBot, text: str, chat_id: int, message_id: int, *, reply_markup=None
) -> None:
    try:
        bot.edit_message_text(
            text, chat_id, message_id, reply_markup=reply_markup
        )
    except ApiTelegramException as error:
        if not is_message_not_modified(error):
            raise
        logger.warning(
            "Validation message unchanged chat_id=%s message_id=%s "
            "action=review_ux reason=%r",
            chat_id, message_id, error.description,
        )
