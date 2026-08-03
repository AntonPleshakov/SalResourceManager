from collections import Counter

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from db.war_stages import get_war_stages_db
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WarActivity, WarPointsCalculator
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


def _personal_war_points_text(user: UserData) -> str:
    stages = get_war_stages_db().get_stages()
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    report = WarPointsCalculator().calculate([user], stages)
    lines = ["<b>Калькулятор очков войны</b>", ""]
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
            f"Итого: <b>{format_points(report.total)}</b>",
            "",
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


def _personal_war_activity_details_text(
    user: UserData, activity: WarActivity
) -> str:
    stages = get_war_stages_db().get_stages()
    details = WarPointsCalculator().calculate_details(user, [activity])[activity]
    lines = [
        f"<b>{activity.title}</b>",
        f"Дни войны: {_activity_days(stages, activity)}",
        f"Очки за одно появление: <b>{format_points(details.points)}</b>",
        "",
        "<i>Исходные данные</i>",
        *(f"• {formatting.escape_html(value)}" for value in details.inputs),
        "",
        "<i>Как получены очки</i>",
        *(
            f"• {formatting.escape_html(calculation)}"
            for calculation in details.calculations
        ),
    ]
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
        keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
        bot.edit_message_text(
            "Сначала заполните свои ресурсы и технологии, "
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

    stages = get_war_stages_db().get_stages()
    activities = _configured_activities(stages)
    details = WarPointsCalculator().calculate_details(user, activities)
    keyboard = InlineKeyboardMarkup(row_width=1)
    for activity in activities:
        keyboard.add(
            Button(
                f"{activity.title} — {format_points(details[activity].points)}",
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

    stages = get_war_stages_db().get_stages()
    if activity not in _configured_activities(stages):
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
