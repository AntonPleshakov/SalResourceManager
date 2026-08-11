"""Administrative game-data report export."""

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db.initializer import get_user_data_db
from logger.app_logger import logger
from reports.game_data import GameDataReport
from tg.utils import Button, empty_filter, get_ids, get_username


def export_game_data(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Game data report requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    try:
        url = GameDataReport().export(get_user_data_db().get_users())
    except Exception as error:
        logger.exception(
            "Unable to export game data report for user_id=%s: %s",
            user_id,
            error,
        )
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось обновить игровые данные",
            show_alert=True,
        )
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("Открыть игровые данные", url=url))
    keyboard.add(Button("Назад к администраторам", "admins").inline())
    bot.edit_message_text(
        "Игровые данные обновлены.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        export_game_data,
        func=empty_filter,
        button="admins/game_data",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
