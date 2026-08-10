from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WAR_STAGES, WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
from tg.utils import Button, empty_filter, get_ids, get_username
from tg.war import personal, public
from tg.war.personal import (
    _activity_days,
    _activity_occurrences,
    _configured_activities,
    _personal_war_activity_details_text,
    _personal_war_points_text,
    personal_war_activity_details,
    personal_war_details_menu,
    personal_war_points,
)
from tg.war.public import _war_points_text, public_war_points


def war_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening war points menu for user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Калькулятор моих очков", "war_calculator").inline())
    keyboard.add(Button("Максимальные очки войны", "war").inline())
    keyboard.add(Button("Назад в меню", "home").inline())
    bot.edit_message_text(
        "<b>Очки войны</b>\n\nВыберите вариант расчёта.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering war handlers")
    bot.register_callback_query_handler(
        war_menu,
        func=empty_filter,
        button="war_menu",
        is_private=True,
        pass_bot=True,
    )
    personal.register_handlers(bot)
    public.register_handlers(bot)


__all__ = [
    "WAR_STAGES",
    "UserData",
    "WarActivity",
    "WarPointsCalculator",
    "_activity_days",
    "_activity_occurrences",
    "_configured_activities",
    "_personal_war_activity_details_text",
    "_personal_war_points_text",
    "_war_points_text",
    "get_user_data_db",
    "explain_forge_occurrences",
    "personal_war_activity_details",
    "personal_war_details_menu",
    "personal_war_points",
    "public_war_points",
    "register_handlers",
    "war_menu",
]
