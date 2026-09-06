from datetime import date, datetime
from html import escape

from telebot import TeleBot
from telebot.types import CallbackQuery

from common.datetime_utils import now, week_started_on
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarPointsCalculator
import tg.war as war
from tg.handlers import HandlerRegistry
from tg.metrics import observe_score_calculation
from tg.rich import (
    back_button,
    details,
    edit_rich_message,
    heading,
    highlight_metric,
    input_rich_message,
    notice,
)
from tg.user_data.common import prompt_for_account_clan
from tg.utils import format_points, get_ids, get_username
from tg.war.supplementary import flasks_summary


def _war_week_started_on(reference: datetime) -> date:
    return week_started_on(reference)


def _resources_updated_since(user: UserData, cutoff: date) -> bool:
    return user.has_war_resource_updates_since(cutoff)


def _war_points_text(clan_id: int, clan_title: str) -> str:
    database = war.get_user_data_db()
    users = database.get_clan_users(clan_id)
    cutoff = _war_week_started_on(now())
    accounted_users = [
        user for user in users if _resources_updated_since(user, cutoff)
    ]
    stale_users = [
        user for user in users if not _resources_updated_since(user, cutoff)
    ]
    clan_flasks = sum(user.flasks.value for user in users)
    logger.info(
        "Calculating war points users=%d accounted_users=%d "
        "stale_users=%d days=%d",
        len(users),
        len(accounted_users),
        len(stale_users),
        len(war.WAR_STAGES),
    )
    with observe_score_calculation("public"):
        report = WarPointsCalculator().calculate(accounted_users, war.WAR_STAGES)
        stale_report = WarPointsCalculator().calculate(
            stale_users,
            war.WAR_STAGES,
        )
    logger.info("War points calculated")
    day_blocks = []
    for day, points in report.points_by_day.items():
        activities = "".join(
            f"<li>{escape(activity.title)}</li>"
            for activity in war.WAR_STAGES[day]
        )
        day_blocks.append(
            details(
                f"День {day} — {format_points(points)}"
                + (
                    f" ({format_points(stale_report.points_by_day[day])})"
                    if stale_users
                    else ""
                ),
                f"<ul>{activities}</ul>",
            )
        )
    activity_rows = "".join(
        "<tr>"
        f"<td>{escape(activity.title)}</td>"
        f'<td align="right"><b>{format_points(points)}</b>'
        + (
            " <i>("
            f"{format_points(stale_report.points_by_activity[activity])})</i>"
            if stale_users
            else ""
        )
        + "</td>"
        "</tr>"
        for activity, points in report.points_by_activity.items()
    )
    parts = [
            heading("Максимальные очки войны"),
            f"<footer>Клан: {escape(clan_title)}</footer>",
            highlight_metric("Итог за войну", format_points(report.total)),
            *(
                (
                    "<p>(По устаревшим данным — "
                    f"<b>{format_points(stale_report.total)}</b> очков)</p>",
                )
                if stale_users
                else ()
            ),
            flasks_summary("Всего колб в клане", clan_flasks),
    ]
    if not accounted_users:
        parts.append(
            notice(
                "Нет актуальных данных: ни у одного аккаунта не обновлены "
                "ресурсы с 03:00 понедельника."
            )
        )
    parts.extend(
        (
            heading("По дням", level=3),
            "<p><b>Дневные оценки независимы и не суммируются.</b> "
            "Ресурсы для каждого дня сначала оцениваются отдельно.</p>",
            *(
                (
                    "<p><i>В скобках указаны возможные очки по "
                    "устаревшим данным.</i></p>",
                )
                if stale_users
                else ()
            ),
            *day_blocks,
            '<table bordered compact><caption>Итого по активностям</caption>',
            "<tr><th>Активность</th><th>Очки</th></tr>",
            activity_rows,
            "<tr><th>Всего</th>"
            f'<th align="right">{format_points(report.total)}'
            + (
                f" <i>({format_points(stale_report.total)})</i>"
                if stale_users
                else ""
            )
            + "</th></tr>",
            "</table>",
            '<table compact><caption>Данные аккаунтов</caption>',
            "<tr><td>Учтено</td>"
            f'<td align="right"><b>{len(accounted_users)}</b></td></tr>',
            "<tr><td>С устаревшими данными</td>"
            f'<td align="right"><b>{len(stale_users)}</b></td></tr>',
            "</table>",
            details(
                "Какие данные считаются устаревшими",
                "<p>Устаревшими считаются данные аккаунтов, у которых ни "
                "один ресурс не обновлён с 03:00 понедельника.</p>",
            ),
            details(
                "Как считается результат",
                "<p>Дневные оценки показывают максимум для каждого дня "
                "по отдельности. Итог за войну учитывает расходуемые "
                "ресурсы только один раз.</p>",
            ),
        )
    )
    return "".join(parts)


def public_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "War points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
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
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(
            (
                _war_points_text(
                    account.clan_id,
                    getattr(account, "clan_title", "") or str(account.clan_id),
                ),
                back_button("⬅️ Очки войны", "war_menu"),
            )
        ),
    )


def register_handlers(bot: TeleBot) -> None:
    HandlerRegistry(bot).private_callback(
        public_war_points,
        button="war",
    )
