from collections import Counter

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
import tg.war as war
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


def _personal_war_points_text(user: UserData) -> str:
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    report = WarPointsCalculator().calculate([user], war.WAR_STAGES)
    lines = [
        "<b>Калькулятор очков войны</b>",
        f"Игровой аккаунт: <b>{formatting.escape_html(user.tag.value)}</b>",
        "<i>Максимум по каждому дню</i>",
        "",
    ]
    for day, points in report.points_by_day.items():
        lines.append(f"<b>День {day}: {format_points(points)}</b>")
        for activity, activity_points in report.points_by_activity_by_day[
            day
        ].items():
            lines.append(
                f"• {activity.title}: <b>{format_points(activity_points)}</b>"
            )
        lines.append("")
    lines.extend(
        [
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
            "Расчёт сделан по вашим сохранённым ресурсам и технологиям.",
        ]
    )
    return "\n".join(lines)


def _configured_activities(stages) -> list[WarActivity]:
    return list(
        dict.fromkeys(
            activity
            for _, activities in sorted(stages.items())
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
    details = calculator.calculate_details(user, [activity])[activity]
    occurrence_points = calculator.calculate_occurrence_points(
        user,
        activity,
        occurrences,
    )
    total_points = sum(occurrence_points)
    lines = [
        f"<b>{activity.title}</b>",
        f"Игровой аккаунт: <b>{formatting.escape_html(user.tag.value)}</b>",
        f"Дни войны: {_activity_days(war.WAR_STAGES, activity)}",
        *(
            f"Появление {index}: <b>{format_points(points)}</b>"
            for index, points in enumerate(occurrence_points, start=1)
        ),
        f"Всего за войну: <b>{format_points(total_points)}</b>",
        "",
    ]
    if activity == WarActivity.FORGE:
        for index, occurrence_details in enumerate(
            explain_forge_occurrences(user, occurrences),
            start=1,
        ):
            lines.extend(
                [
                    f"<i>Появление {index}</i>",
                    *(
                        f"• {formatting.escape_html(value)}"
                        for value in occurrence_details.inputs
                    ),
                    *(
                        f"• {formatting.escape_html(calculation)}"
                        for calculation in occurrence_details.calculations
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "<i>Учёт повторений</i>",
                "• Монеты считаются безлимитными",
                "• К четвёртому дню уровень повышается на 1, только если "
                "исходный уровень не выше 22",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "<i>Исходные данные</i>",
            *(f"• {formatting.escape_html(value)}" for value in details.inputs),
            "",
            "<i>Как получены очки</i>",
            *(
                f"• {formatting.escape_html(calculation)}"
                for calculation in details.calculations
            ),
            "",
            "<i>Учёт повторений</i>",
            f"• Расходуемая часть: "
            f"{format_points(details.consumable_points)} — один раз",
            f"• Повторяемая часть: {format_points(details.repeatable_points)} × "
            f"{occurrences}",
        ]
    )
    return "\n".join(lines)


def personal_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Personal war points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    user = war.get_user_data_db().get_user(user_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user is None:
        keyboard.add(
            Button(
                "🎮 Добавить или выбрать аккаунт", "accounts/war_calculator"
            ).inline()
        )
        keyboard.row(
            Button("📦 Ресурсы", "resources").inline(),
            Button("🔬 Технологии", "technologies").inline(),
        )
        keyboard.add(Button("🐾 Настроить питомцев", "pets").inline())
        keyboard.add(Button("⬅️ Назад к очкам войны", "war_menu").inline())
        bot.edit_message_text(
            "Сначала заполните свои ресурсы, технологии и настройки питомцев, "
            "чтобы бот мог рассчитать очки войны.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    keyboard.add(
        Button("🔄 Сменить аккаунт", "accounts/war_calculator").inline()
    )
    keyboard.add(Button("🧮 Подробный расчёт", "war_calculator/details").inline())
    keyboard.row(
        Button("📦 Ресурсы", "resources").inline(),
        Button("🔬 Технологии", "technologies").inline(),
    )
    keyboard.add(Button("🐾 Настроить питомцев", "pets").inline())
    keyboard.add(Button("⬅️ Назад к очкам войны", "war_menu").inline())
    bot.edit_message_text(
        _personal_war_points_text(user),
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def personal_war_details_menu(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = war.get_user_data_db().get_user(user_id)
    if user is None:
        personal_war_points(callback_query, bot)
        return

    activities = _configured_activities(war.WAR_STAGES)
    report = WarPointsCalculator().calculate([user], war.WAR_STAGES)
    keyboard = InlineKeyboardMarkup(row_width=1)
    for activity in activities:
        keyboard.add(
            Button(
                f"{activity.title} — "
                f"{format_points(report.points_by_activity[activity])}",
                f"war_calculator/details/{activity.value}",
            ).inline()
        )
    keyboard.add(Button("⬅️ Назад к отчёту по дням", "war_calculator").inline())
    bot.edit_message_text(
        "<b>Подробный расчёт</b>\n\n"
        f"Игровой аккаунт: <b>{formatting.escape_html(user.tag.value)}</b>\n\n"
        "Выберите активность, чтобы увидеть использованные ресурсы и формулу.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


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

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("📋 Активности", "war_calculator/details").inline(),
        Button("📊 По дням", "war_calculator").inline(),
    )
    bot.edit_message_text(
        _personal_war_activity_details_text(user, activity),
        chat_id,
        message_id,
        reply_markup=keyboard,
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
