from collections import Counter
from html import escape

from telebot import TeleBot
from telebot.types import CallbackQuery

from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
import tg.war as war
from tg.metrics import observe_score_calculation
from tg.rich import button_row, callback_button, input_rich_message
from tg.utils import empty_filter, format_points, get_ids, get_username


def _personal_war_points_text(user: UserData) -> str:
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    with observe_score_calculation("personal_summary"):
        report = WarPointsCalculator().calculate([user], war.WAR_STAGES)
    day_rows = []
    for day, points in report.points_by_day.items():
        activities = "<br>".join(
            f"{escape(activity.title)}: <b>{format_points(activity_points)}</b>"
            for activity, activity_points in report.points_by_activity_by_day[
                day
            ].items()
        )
        day_rows.append(
            "<tr>"
            f'<td align="center"><b>{day}</b></td>'
            f"<td>{activities}</td>"
            f'<td align="right"><b>{format_points(points)}</b></td>'
            "</tr>"
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
            "<h2>Калькулятор очков войны</h2>",
            "<p>Игровой аккаунт: "
            f"<b>{escape(str(user.tag.value))}</b><br>"
            "<i>Максимум по каждому дню</i></p>",
            '<table bordered striped compact><caption>По дням</caption>',
            "<tr><th>День</th><th>Активности</th><th>Очки</th></tr>",
            *day_rows,
            "</table>",
            '<table bordered compact><caption>Итого по активностям</caption>',
            "<tr><th>Активность</th><th>Очки</th></tr>",
            activity_rows,
            "<tr><th>Всего</th>"
            f'<th align="right">{format_points(report.total)}</th></tr>',
            "</table>",
            "<details><summary>Как считается результат</summary>",
            "<p>Максимум каждого дня считается отдельно. В итогах "
            "расходуемые ресурсы учитываются один раз.</p>",
            "<p>Расчёт сделан по вашим сохранённым ресурсам и "
            "технологиям.</p></details>",
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


def _personal_war_activity_details_text(
    user: UserData, activity: WarActivity
) -> str:
    occurrences = _activity_occurrences(war.WAR_STAGES, activity)
    calculator = WarPointsCalculator()
    with observe_score_calculation("activity_details"):
        details = calculator.calculate_details(user, [activity])[activity]
        occurrence_points = calculator.calculate_occurrence_points(
            user,
            activity,
            occurrences,
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
        f"<h2>{escape(activity.title)}</h2>",
        "<p>Игровой аккаунт: "
        f"<b>{escape(str(user.tag.value))}</b><br>"
        f"Дни войны: {escape(_activity_days(war.WAR_STAGES, activity))}</p>",
        '<table bordered compact><caption>Очки</caption>',
        occurrence_rows,
        "<tr><th>Всего за войну</th>"
        f'<th align="right">{format_points(total_points)}</th></tr>',
        "</table>",
    ]
    if activity == WarActivity.FORGE:
        for index, occurrence_details in enumerate(
            explain_forge_occurrences(user, occurrences),
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
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        rich_message=input_rich_message(parts),
    )


def personal_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Personal war points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    user = war.get_user_data_db().get_user(user_id)
    if user is None:
        _edit_rich_message(
            bot,
            chat_id,
            message_id,
            [
                "<h2>Калькулятор очков войны</h2>",
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
                button_row(
                    (
                        callback_button(
                            "⬅️ Назад к очкам войны",
                            "war_menu",
                        ),
                    ),
                    align="left",
                ),
            ],
        )
        return

    parts = [
        _personal_war_points_text(user),
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
        button_row(
            (
                callback_button(
                    "⬅️ Назад к очкам войны", "war_menu"
                ),
            ),
            align="left",
        ),
    ]
    _edit_rich_message(bot, chat_id, message_id, parts)


def personal_war_details_menu(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = war.get_user_data_db().get_user(user_id)
    if user is None:
        personal_war_points(callback_query, bot)
        return

    activities = _configured_activities(war.WAR_STAGES)
    with observe_score_calculation("personal_details"):
        report = WarPointsCalculator().calculate([user], war.WAR_STAGES)
    parts = [
        "<h2>Подробный расчёт</h2>",
        "<p>Игровой аккаунт: "
        f"<b>{escape(str(user.tag.value))}</b></p>",
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
    parts.append(
        button_row(
            (
                callback_button(
                    "⬅️ Назад к отчёту по дням",
                    "war_calculator",
                ),
            ),
            align="left",
        )
    )
    _edit_rich_message(bot, chat_id, message_id, parts)


def personal_war_activity_details(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = war.get_user_data_db().get_user(user_id)
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
            _personal_war_activity_details_text(user, activity),
            button_row(
                (
                    callback_button(
                        "📋 Активности", "war_calculator/details"
                    ),
                    callback_button("📊 По дням", "war_calculator"),
                )
            ),
        ],
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        personal_war_points,
        func=empty_filter,
        button="war_calculator",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        personal_war_details_menu,
        func=empty_filter,
        button="war_calculator/details",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        personal_war_activity_details,
        func=empty_filter,
        button=r"war_calculator/details/[a-z_]+",
        is_private=True,
        pass_bot=True,
    )
