from collections import Counter
from html import escape
import sqlite3

from telebot import TeleBot
from telebot.types import CallbackQuery

from db.initializer import get_access_group_db
from logger.app_logger import logger
from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war import WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
import tg.war as war
from tg.handlers import HandlerRegistry
from tg.metrics import observe_score_calculation
from tg.rich import (
    account_context,
    back_button,
    button_row,
    callback_button,
    details as rich_details,
    edit_rich_message,
    heading,
    highlight_metric,
    input_rich_message,
)
from tg.utils import format_points, get_ids, get_username
from tg.war.supplementary import flasks_summary


def _personal_war_points_text(
    user: UserData,
    clan_technologies: ClanTechnologies | None = None,
) -> str:
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    with observe_score_calculation("personal_summary"):
        report = WarPointsCalculator(clan_technologies).calculate(
            [user], war.WAR_STAGES
        )
    day_blocks = []
    for day, points in report.points_by_day.items():
        activities = "".join(
            f"<li>{escape(activity.title)}: "
            f"<b>{format_points(activity_points)}</b></li>"
            for activity, activity_points in report.points_by_activity_by_day[
                day
            ].items()
        )
        day_blocks.append(
            rich_details(
                f"День {day} — {format_points(points)}",
                f"<ul>{activities}</ul>",
            )
        )
    activity_rows = "".join(
        "<tr>"
        f"<td>{escape(activity.title)}</td>"
        f'<td align="right"><b>{format_points(points)}</b></td>'
        "</tr>"
        for activity, points in report.points_by_activity.items()
    )
    return "".join(
        (
            heading("Калькулятор очков войны"),
            account_context(str(user.tag.value)),
            highlight_metric("Итог за войну", format_points(report.total)),
            flasks_summary("Колбы аккаунта", user.flasks.value),
            heading("По дням", level=3),
            "<p><b>Дневные оценки независимы и не суммируются.</b> "
            "Ресурсы для каждого дня сначала оцениваются отдельно.</p>",
            *day_blocks,
            '<table bordered compact><caption>Итого по активностям</caption>',
            "<tr><th>Активность</th><th>Очки</th></tr>",
            activity_rows,
            "<tr><th>Всего</th>"
            f'<th align="right">{format_points(report.total)}</th></tr>',
            "</table>",
            rich_details(
                "Как считается результат",
                "<p>Дневные оценки показывают максимум для каждого дня "
                "по отдельности. Итог за войну учитывает расходуемые "
                "ресурсы только один раз.</p>"
                "<p>Расчёт сделан по сохранённым ресурсам и "
                "технологиям.</p>",
            ),
        )
    )


def _configured_activities(stages) -> list[WarActivity]:
    return list(
        dict.fromkeys(
            activity
            for activities in (stages[day] for day in sorted(stages))
            for activity in activities
        )
    )


def _activity_days(stages, selected_activity: WarActivity) -> str:
    days = []
    for day, activities in sorted(stages.items()):
        count = Counter(activities)[selected_activity]
        if count:
            days.append(f"{day} (×{count})" if count > 1 else str(day))
    return ", ".join(days)


def _activity_occurrences(stages, selected_activity: WarActivity) -> int:
    return sum(
        activities.count(selected_activity) for activities in stages.values()
    )


def _activity_day_numbers(stages, selected_activity: WarActivity) -> list[int]:
    return [
        day
        for day, activities in sorted(stages.items())
        for activity in activities
        if activity == selected_activity
    ]


def _active_clan_technologies(user_id: int) -> ClanTechnologies:
    account = war.get_user_data_db().get_active_account(user_id)
    if account is None or account.clan_id is None:
        return ClanTechnologies()
    try:
        return get_access_group_db().get_clan_technologies(account.clan_id)
    except RuntimeError:
        return ClanTechnologies()
    except sqlite3.ProgrammingError as error:
        if "closed" not in str(error).casefold():
            raise
        return ClanTechnologies()


def _personal_war_activity_details_text(
    user: UserData,
    activity: WarActivity,
    clan_technologies: ClanTechnologies | None = None,
) -> str:
    occurrences = _activity_occurrences(war.WAR_STAGES, activity)
    technologies = clan_technologies or ClanTechnologies()
    calculator = WarPointsCalculator(technologies)
    with observe_score_calculation("activity_details"):
        details = calculator.calculate_details(user, [activity])[activity]
        occurrence_points = calculator.calculate_occurrence_points(
            user,
            activity,
            occurrences,
            _activity_day_numbers(war.WAR_STAGES, activity),
        )
        total_points = sum(occurrence_points)
    occurrence_rows = "".join(
        "<tr>"
        f"<td>Появление {index}</td>"
        f'<td align="right"><b>{format_points(points)}</b></td>'
        "</tr>"
        for index, points in enumerate(occurrence_points, start=1)
    )
    parts = [
        heading(activity.title),
        account_context(str(user.tag.value)),
        f"<p>Дни войны: {escape(_activity_days(war.WAR_STAGES, activity))}</p>",
        highlight_metric("Всего за войну", format_points(total_points)),
        '<table bordered compact><caption>Очки</caption>',
        occurrence_rows,
        "</table>",
    ]
    if activity == WarActivity.FORGE:
        for index, occurrence_details in enumerate(
            explain_forge_occurrences(user, occurrences, technologies),
            start=1,
        ):
            items = "".join(
                f"<li>{escape(str(value))}</li>"
                for value in (
                    *occurrence_details.inputs,
                    *occurrence_details.calculations,
                )
            )
            parts.append(
                f"<details><summary>Появление {index}: расчёт</summary>"
                f"<ul>{items}</ul></details>"
            )
        parts.append(
            "<details><summary>Учёт повторений</summary><ul>"
            "<li>Монеты считаются безлимитными</li>"
            "<li>К четвёртому дню уровень повышается на 1, только если "
            "исходный уровень не выше 22</li>"
            "</ul></details>"
        )
        return "".join(parts)

    input_items = "".join(
        f"<li>{escape(str(value))}</li>" for value in details.inputs
    )
    calculation_items = "".join(
        f"<li>{escape(str(calculation))}</li>"
        for calculation in details.calculations
    )
    parts.extend(
        (
            "<details><summary>Исходные данные</summary>"
            f"<ul>{input_items}</ul></details>",
            "<details><summary>Как получены очки</summary>"
            f"<ul>{calculation_items}</ul></details>",
            "<details><summary>Учёт повторений</summary><ul>"
            "<li>Расходуемая часть: "
            f"{format_points(details.consumable_points)} — один раз</li>"
            "<li>Повторяемая часть: "
            f"{format_points(details.repeatable_points)} × {occurrences}</li>"
            "</ul></details>",
        )
    )
    return "".join(parts)


def _edit_rich_message(
    bot: TeleBot,
    chat_id: int,
    message_id: int,
    parts: list[str],
) -> None:
    edit_rich_message(bot, chat_id, message_id, input_rich_message(parts))


def personal_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Personal war points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    user = war.get_user_data_db().get_assigned_user(user_id)
    if user is None:
        _edit_rich_message(
            bot,
            chat_id,
            message_id,
            [
                heading("Калькулятор очков войны"),
                "<p>Сначала добавьте или выберите игровой аккаунт, затем "
                "заполните его ресурсы, технологии и настройки питомцев.</p>",
                button_row(
                    (
                        callback_button(
                            "🎮 Добавить или выбрать аккаунт",
                            "accounts/war_calculator",
                            style="primary",
                        ),
                    )
                ),
                button_row(
                    (
                        callback_button("📦 Ресурсы", "resources"),
                        callback_button("🔬 Технологии", "technologies"),
                    )
                ),
                button_row(
                    (callback_button("🐾 Настроить питомцев", "pets"),)
                ),
                back_button("⬅️ Очки войны", "war_menu"),
            ],
        )
        return

    parts = [
        _personal_war_points_text(user, _active_clan_technologies(user_id)),
        button_row(
            (
                callback_button(
                    "🔄 Сменить аккаунт", "accounts/war_calculator"
                ),
                callback_button(
                    "🧮 Подробный расчёт",
                    "war_calculator/details",
                    style="primary",
                ),
            )
        ),
        button_row(
            (
                callback_button("📦 Ресурсы", "resources"),
                callback_button("🔬 Технологии", "technologies"),
            )
        ),
        button_row((callback_button("🐾 Настроить питомцев", "pets"),)),
        back_button("⬅️ Очки войны", "war_menu"),
    ]
    _edit_rich_message(bot, chat_id, message_id, parts)


def personal_war_details_menu(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = war.get_user_data_db().get_assigned_user(user_id)
    if user is None:
        personal_war_points(callback_query, bot)
        return

    activities = _configured_activities(war.WAR_STAGES)
    with observe_score_calculation("personal_details"):
        report = WarPointsCalculator(
            _active_clan_technologies(user_id)
        ).calculate([user], war.WAR_STAGES)
    parts = [
        heading("Подробный расчёт"),
        account_context(str(user.tag.value)),
        "<p>Выберите активность, чтобы увидеть использованные ресурсы "
        "и формулу.</p>",
    ]
    for activity in activities:
        parts.append(
            button_row(
                (
                    callback_button(
                        f"{activity.title} — "
                        f"{format_points(report.points_by_activity[activity])}",
                        f"war_calculator/details/{activity.value}",
                    ),
                )
            )
        )
    parts.append(back_button("⬅️ Отчёт по дням", "war_calculator"))
    _edit_rich_message(bot, chat_id, message_id, parts)


def personal_war_activity_details(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = war.get_user_data_db().get_assigned_user(user_id)
    if user is None:
        personal_war_points(callback_query, bot)
        return

    try:
        activity = WarActivity(callback_query.data.rsplit("/", maxsplit=1)[-1])
    except ValueError:
        logger.warning(
            "Unknown war activity details requested by user_id=%s data=%s",
            user_id,
            callback_query.data,
        )
        bot.answer_callback_query(
            callback_query.id,
            "Активность не найдена",
            show_alert=True,
        )
        return

    if activity not in _configured_activities(war.WAR_STAGES):
        bot.answer_callback_query(
            callback_query.id,
            "Активность не используется в текущей войне",
            show_alert=True,
        )
        return

    _edit_rich_message(
        bot,
        chat_id,
        message_id,
        [
            _personal_war_activity_details_text(
                user, activity, _active_clan_technologies(user_id)
            ),
            button_row(
                (
                    callback_button(
                        "📋 Активности", "war_calculator/details"
                    ),
                    callback_button("📊 По дням", "war_calculator"),
                )
            ),
            back_button("🏠 Главное меню", "home"),
        ],
    )


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.private_callback(
        personal_war_points,
        button="war_calculator",
    )
    handlers.private_callback(
        personal_war_details_menu,
        button="war_calculator/details",
    )
    handlers.private_callback(
        personal_war_activity_details,
        button=r"war_calculator/details/[a-z_]+",
    )
