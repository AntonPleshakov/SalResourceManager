from typing import Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.initializer import get_admins_db, get_user_data_db
from logger.app_logger import logger
from tg.onboarding import show_new_user_welcome
from tg.releases import mark_current_release_seen, show_unseen_releases
from tg.utils import Button, get_ids, get_username


def _show_onboarding(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    if not show_new_user_welcome(message, bot):
        return False
    mark_current_release_seen(message)
    return True


def show_home_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    database = get_user_data_db()
    accounts = database.get_accounts(user_id)
    active_account = next(
        (account for account in accounts if account.is_active),
        None,
    )
    keyboard = InlineKeyboardMarkup()
    keyboard.row(Button("🎮 Игровые аккаунты", "accounts").inline())
    keyboard.row(
        Button("📦 Ресурсы", "resources").inline(),
        Button("🔬 Технологии", "technologies").inline(),
    )
    keyboard.row(
        Button("🐾 Питомцы", "pets").inline(),
        Button("⚔️ Очки войны", "war_menu").inline(),
    )
    reminders_enabled = database.reminders_enabled(user_id)
    keyboard.row(
        Button(
            "🔕 Выключить напоминания"
            if reminders_enabled
            else "🔔 Включить напоминания",
            "reminders/toggle",
        ).inline()
    )
    keyboard.row(Button("🆕 Что нового", "releases").inline())
    logger.debug(
        "Opening home menu for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    if get_admins_db().has_admin_access(user_id):
        keyboard.row(Button("🛠 Админ-панель", "admins").inline())
    text_lines = []
    if active_account is not None:
        text_lines.append(
            "Игровой аккаунт: "
            f"<b>{formatting.escape_html(active_account.tag)}</b>"
        )
        if active_account.clan_title:
            text_lines.append(
                "Клан: "
                f"<b>{formatting.escape_html(active_account.clan_title)}</b>"
            )
        if len(accounts) > 1:
            text_lines.append(f"Всего аккаунтов: {len(accounts)}")
        text_lines.append("")
    text_lines.append("Выберите раздел.")
    text_lines.extend(
        (
            "",
            "Настройка напоминаний влияет только на автоматическое "
            "уведомление по понедельникам и не отключает сообщения "
            "администраторов.",
            "Пожалуйста, не выключайте уведомления от бота в Telegram, "
            "чтобы не пропустить сообщения администраторов.",
        )
    )
    text = "\n".join(text_lines)
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def start(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    if show_unseen_releases(message, bot):
        return
    show_home_menu(message, bot)


def home(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    show_home_menu(message, bot)


def toggle_reminders(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = get_ids(callback_query)[0]
    database = get_user_data_db()
    enabled = not database.reminders_enabled(user_id)
    database.set_reminders_enabled(user_id, enabled)
    logger.info(
        "Monday resource reminders toggled enabled=%s for user_id=%s username=%s",
        enabled,
        user_id,
        get_username(callback_query),
    )
    show_home_menu(callback_query, bot)
