from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from db.war_stages import get_war_stages_db
from logger.app_logger import logger
from resources.user_data import UserData
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


def _personal_war_points_text(user: UserData) -> str:
    stages = get_war_stages_db().get_stages()
    logger.info("Calculating personal war points user_id=%s", user.user_id.value)
    report = WarPointsCalculator().calculate([user], stages)
    lines = ["<b>Калькулятор очков войны</b>", ""]
    for day, points in report.points_by_day.items():
        activities = ", ".join(activity.title for activity in stages[day])
        lines.append(f"День {day}: <b>{format_points(points)}</b> — {activities}")
    lines.extend(
        [
            "",
            f"Итого: <b>{format_points(report.total)}</b>",
            "",
            "Расчёт сделан по вашим сохранённым ресурсам и технологиям.",
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
        keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
        bot.edit_message_text(
            "Сначала заполните свои ресурсы и технологии, "
            "чтобы бот мог рассчитать очки войны.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    keyboard.add(Button("Обновить ресурсы", "resources").inline())
    keyboard.add(Button("Обновить технологии", "technologies").inline())
    keyboard.add(Button("Назад к очкам войны", "war_menu").inline())
    bot.edit_message_text(
        _personal_war_points_text(user),
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
        public_war_points,
        func=empty_filter,
        button="war",
        is_private=True,
        pass_bot=True,
    )
