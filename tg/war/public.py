from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from logger.app_logger import logger
from resources.war import WarPointsCalculator
import tg.war as war
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


def _war_points_text() -> str:
    users = war.get_user_data_db().get_users()
    logger.info(
        "Calculating war points users=%d days=%d",
        len(users),
        len(war.WAR_STAGES),
    )
    report = WarPointsCalculator().calculate(users, war.WAR_STAGES)
    logger.info("War points calculated")
    lines = [
        "<b>Максимальные очки войны</b>",
        "<i>Максимум по каждому дню</i>",
        "",
    ]
    for day, points in report.points_by_day.items():
        activities = ", ".join(
            activity.title for activity in war.WAR_STAGES[day]
        )
        lines.append(f"День {day}: <b>{format_points(points)}</b> — {activities}")
    lines.extend(
        [
            "",
            "<b>Итого по активностям</b>",
            *(
                f"• {activity.title}: <b>{format_points(points)}</b>"
                for activity, points in report.points_by_activity.items()
            ),
            "",
            f"Всего: <b>{format_points(report.total)}</b>",
            "",
            "Максимум каждого дня считается отдельно. В итогах расходуемые "
            "ресурсы учитываются один раз.",
        ]
    )
    return "\n".join(lines)


def public_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "War points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
    bot.edit_message_text(
        _war_points_text(), chat_id, message_id, reply_markup=keyboard
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        public_war_points,
        func=empty_filter,
        button="war",
        is_private=True,
        pass_bot=True,
    )
