from datetime import date, timedelta

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from common.datetime_utils import now
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarPointsCalculator
import tg.war as war
from tg.metrics import observe_score_calculation
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


WAR_ACCOUNT_STALE_AFTER_DAYS = 3


def _resources_updated_after(user: UserData, cutoff: date) -> bool:
    updated_on = user.get_last_updated_on()
    return updated_on is not None and updated_on >= cutoff


def _war_points_text() -> str:
    users = war.get_user_data_db().get_users()
    cutoff = now().date() - timedelta(days=WAR_ACCOUNT_STALE_AFTER_DAYS)
    accounted_users = [
        user for user in users if _resources_updated_after(user, cutoff)
    ]
    stale_users_count = len(users) - len(accounted_users)
    logger.info(
        "Calculating war points users=%d accounted_users=%d "
        "stale_users=%d days=%d",
        len(users),
        len(accounted_users),
        stale_users_count,
        len(war.WAR_STAGES),
    )
    with observe_score_calculation("public"):
        report = WarPointsCalculator().calculate(accounted_users, war.WAR_STAGES)
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
            f"Учтено аккаунтов: <b>{len(accounted_users)}</b>",
            "Не учтено (ресурсы не обновлялись более "
            f"{WAR_ACCOUNT_STALE_AFTER_DAYS} дней): "
            f"<b>{stale_users_count}</b>",
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
    keyboard.add(Button("⬅️ Назад к очкам войны", "war_menu").inline())
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
