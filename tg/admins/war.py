from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from db.user_data import get_user_data_db
from db.war_stages import get_war_stages_db
from logger.app_logger import logger
from resources.war import WarActivity, WarPointsCalculator
from tg.utils import Button, empty_filter, format_points, get_ids, get_username


def _edit_message(
    callback_query: CallbackQuery, bot: TeleBot, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    _, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)


def war_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Максимальные очки войны", "war/points").inline())
    keyboard.add(Button("Этапы войны", "war/stages").inline())
    keyboard.add(Button("Назад к администраторам", "admins").inline())
    _edit_message(callback_query, bot, "Управление войной", keyboard)


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
    lines.extend(
        [
            "",
            f"Итого: <b>{format_points(report.total)}</b>",
        ]
    )
    return "\n".join(lines)


def public_war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад в меню", "home").inline())
    _edit_message(callback_query, bot, _war_points_text(), keyboard)


def war_points(callback_query: CallbackQuery, bot: TeleBot) -> None:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад к войне", "war/admin").inline())
    _edit_message(callback_query, bot, _war_points_text(), keyboard)


def war_stages(callback_query: CallbackQuery, bot: TeleBot) -> None:
    stages = get_war_stages_db().get_stages()
    keyboard = InlineKeyboardMarkup(row_width=1)
    for day, activities in stages.items():
        title = f"День {day}: {', '.join(activity.title for activity in activities)}"
        keyboard.add(Button(title, f"war/stages/{day}").inline())
    keyboard.add(Button("Назад к войне", "war/admin").inline())
    _edit_message(callback_query, bot, "Выберите день для изменения этапов.", keyboard)


def _war_stage_options(
    callback_query: CallbackQuery, bot: TeleBot, day: int
) -> None:
    activities = get_war_stages_db().get_stages().get(day)
    if activities is None:
        bot.answer_callback_query(callback_query.id, "День войны не найден")
        return

    keyboard = InlineKeyboardMarkup(row_width=1)
    for position, activity in enumerate(activities):
        keyboard.add(
            Button(
                f"{position + 1}. {activity.title}",
                f"war/stages/{day}/{position}",
            ).inline()
        )
    keyboard.add(Button("Назад к этапам", "war/stages").inline())
    _edit_message(callback_query, bot, f"День {day}. Выберите этап.", keyboard)


def war_stage_options(callback_query: CallbackQuery, bot: TeleBot) -> None:
    day = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
    _war_stage_options(callback_query, bot, day)


def activity_options(callback_query: CallbackQuery, bot: TeleBot) -> None:
    _, _, day, position = callback_query.data.split("/")
    day, position = int(day), int(position)
    keyboard = InlineKeyboardMarkup(row_width=1)
    for activity in WarActivity:
        keyboard.add(
            Button(activity.title, f"war/set/{day}/{position}/{activity.value}").inline()
        )
    keyboard.add(Button("Назад к этапам дня", f"war/stages/{day}").inline())
    _edit_message(callback_query, bot, "Выберите активность.", keyboard)


def set_activity(callback_query: CallbackQuery, bot: TeleBot) -> None:
    _, _, day, position, activity = callback_query.data.split("/")
    logger.info(
        "War activity update requested admin_id=%s username=%s day=%s position=%s activity=%s",
        callback_query.from_user.id,
        get_username(callback_query),
        day,
        position,
        activity,
    )
    get_war_stages_db().set_activity(
        int(day), int(position), WarActivity(activity)
    )
    bot.answer_callback_query(callback_query.id, "Этап войны сохранён")
    _war_stage_options(callback_query, bot, int(day))


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering war administration handlers")
    bot.register_callback_query_handler(
        war_menu,
        func=empty_filter,
        button="war/admin",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        public_war_points,
        func=empty_filter,
        button="war",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        war_points,
        func=empty_filter,
        button="war/points",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        war_stages,
        func=empty_filter,
        button="war/stages",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        war_stage_options,
        func=empty_filter,
        button=r"war/stages/\d+",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        activity_options,
        func=empty_filter,
        button=r"war/stages/\d+/[0-2]",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        set_activity,
        func=empty_filter,
        button=r"war/set/\d+/[0-2]/[a-z_]+",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
