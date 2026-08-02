from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from db.war_stages import get_war_stages_db
from logger.app_logger import logger
from resources.war import WarPointsCalculator
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


def _war_points_text() -> str:
    stages = get_war_stages_db().get_stages()
    users = get_user_data_db().get_users()
    logger.info("Calculating war points users=%d days=%d", len(users), len(stages))
    report = WarPointsCalculator().calculate(users, stages)
    logger.info("War points calculated")
    lines = ["<b>Максимальные очки войны</b>", ""]
    for day, points in report.points_by_day.items():
        activities = ", ".join(activity.title for activity in stages[day])
        lines.append(f"День {day}: <b>{format_points(points)}</b> — {activities}")
    lines.extend(["", f"Итого: <b>{format_points(report.total)}</b>"])
    return "\n".join(lines)


def public_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "War points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад в меню", "home").inline())
    bot.edit_message_text(
        _war_points_text(), chat_id, message_id, reply_markup=keyboard
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering public war handler")
    bot.register_callback_query_handler(
        public_war_points,
        func=empty_filter,
        button="war",
        is_private=True,
        pass_bot=True,
    )
