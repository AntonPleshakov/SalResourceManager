from collections import Counter

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WAR_STAGES, WarActivity, WarPointsCalculator
from resources.war_rules.forge import explain_forge_occurrences
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


def _war_points_text() -> str:
    users = get_user_data_db().get_users()
    logger.info(
        "Calculating war points users=%d days=%d",
        len(users),
        len(WAR_STAGES),
    )
    report = WarPointsCalculator().calculate(users, WAR_STAGES)
    logger.info("War points calculated")
    lines = [
        "<b>Максимальные очки войны</b>",
        "<i>Максимум по каждому дню</i>",
        "",
    ]
    for day, points in report.points_by_day.items():
        activities = ", ".join(activity.title for activity in WAR_STAGES[day])
        lines.append(f"День {day}: <b>{format_points(points)}</b> — {activities}")
    lines.extend(
        [
            "",
            "<b>Итого по активностям</b>",
            *(
                f"• {activity.title}: "
                f"<b>{format_points(points)}</b>"
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


def _personal_war_points_text(user: UserData) -> str:
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    report = WarPointsCalculator().calculate([user], WAR_STAGES)
    lines = [
        "<b>Калькулятор очков войны</b>",
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
                f"• {activity.title}: "
                f"<b>{format_points(points)}</b>"
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
    occurrences = _activity_occurrences(WAR_STAGES, activity)
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
        f"Дни войны: {_activity_days(WAR_STAGES, activity)}",
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


def personal_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Personal war points requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    user = get_user_data_db().get_user(user_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    if user is None:
        keyboard.add(Button("Заполнить ресурсы", "resources").inline())
        keyboard.add(Button("Заполнить технологии", "technologies").inline())
        keyboard.add(Button("Настроить питомцев", "pets").inline())
        keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
        bot.edit_message_text(
            "Сначала заполните свои ресурсы, технологии и настройки питомцев, "
            "чтобы бот мог рассчитать очки войны.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    keyboard.add(
        Button("Подробный расчёт", "war_calculator/details").inline()
    )
    keyboard.add(Button("Обновить ресурсы", "resources").inline())
    keyboard.add(Button("Обновить технологии", "technologies").inline())
    keyboard.add(Button("Настроить питомцев", "pets").inline())
    keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
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
    user = get_user_data_db().get_user(user_id)
    if user is None:
        personal_war_points(callback_query, bot)
        return

    activities = _configured_activities(WAR_STAGES)
    report = WarPointsCalculator().calculate([user], WAR_STAGES)
    keyboard = InlineKeyboardMarkup(row_width=1)
    for activity in activities:
        keyboard.add(
            Button(
                f"{activity.title} — "
                f"{format_points(report.points_by_activity[activity])}",
                f"war_calculator/details/{activity.value}",
            ).inline()
        )
    keyboard.add(Button("Назад к отчёту по дням", "war_calculator").inline())
    bot.edit_message_text(
        "<b>Подробный расчёт</b>\n\n"
        "Выберите активность, чтобы увидеть использованные ресурсы и формулу.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def personal_war_activity_details(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = get_user_data_db().get_user(user_id)
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

    if activity not in _configured_activities(WAR_STAGES):
        bot.answer_callback_query(
            callback_query.id,
            "Активность не используется в текущей войне",
            show_alert=True,
        )
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("К списку активностей", "war_calculator/details").inline(),
        Button("К отчёту по дням", "war_calculator").inline(),
    )
    bot.edit_message_text(
        _personal_war_activity_details_text(user, activity),
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering public war handler")
    bot.register_callback_query_handler(
        war_menu,
        func=empty_filter,
        button="war_menu",
        is_private=True,
        pass_bot=True,
    )
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
    bot.register_callback_query_handler(
        public_war_points,
        func=empty_filter,
        button="war",
        is_private=True,
        pass_bot=True,
    )
