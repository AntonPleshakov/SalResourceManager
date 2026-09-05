from datetime import date, datetime

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from common.datetime_utils import now, week_started_on
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarPointsCalculator
import tg.war as war
from tg.handlers import HandlerRegistry
from tg.metrics import observe_score_calculation
from tg.user_data.common import prompt_for_account_clan
from tg.utils import Button, format_points, get_ids, get_username


def _war_week_started_on(reference: datetime) -> date:
    return week_started_on(reference)


def _resources_updated_since(user: UserData, cutoff: date) -> bool:
    return user.has_resource_updates_since(cutoff)


def _war_points_text(clan_id: int) -> str:
    database = war.get_user_data_db()
    users = database.get_clan_users(clan_id)
    cutoff = _war_week_started_on(now())
    accounted_users = [
        user for user in users if _resources_updated_since(user, cutoff)
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
            "Не учтено (ни один ресурс не обновлён с 03:00 понедельника): "
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
    account = war.get_user_data_db().get_active_account(user_id)
    if account is None:
        bot.answer_callback_query(
            callback_query.id,
            "Сначала создайте игровой аккаунт",
            show_alert=True,
        )
        return
    if account.clan_id is None:
        prompt_for_account_clan(callback_query, bot, account.account_id)
        return
    bot.edit_message_text(
        _war_points_text(account.clan_id),
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def register_handlers(bot: TeleBot) -> None:
    HandlerRegistry(bot).private_callback(
        public_war_points,
        button="war",
    )
