from telebot import TeleBot
from telebot.types import CallbackQuery

from db.initializer import get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WAR_STAGES, WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
from tg.handlers import HandlerRegistry
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    heading,
    input_rich_message,
)
from tg.utils import get_ids, get_username
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
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(
            (
                heading("Очки войны"),
                "<p>Выберите вариант расчёта.</p>",
                button_row(
                    (
                        callback_button(
                            "🧮 Мои очки",
                            "war_calculator",
                            style="primary",
                        ),
                        callback_button("👥 Общие", "war"),
                    )
                ),
                back_button("⬅️ Главное меню", "home"),
            )
        ),
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering war handlers")
    HandlerRegistry(bot).private_callback(
        war_menu,
        button="war_menu",
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
