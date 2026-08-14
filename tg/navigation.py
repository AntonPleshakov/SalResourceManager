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
    accounts = get_user_data_db().get_accounts(user_id)
    active_account = next(
        (account for account in accounts if account.is_active),
        None,
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Игровые аккаунты", "accounts").inline())
    keyboard.add(Button("Ресурсы", "resources").inline())
    keyboard.add(Button("Технологии", "technologies").inline())
    keyboard.add(Button("Питомцы", "pets").inline())
    keyboard.add(Button("Очки войны", "war_menu").inline())
    keyboard.add(Button("Что нового", "releases").inline())
    logger.debug(
        "Opening home menu for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    if get_admins_db().is_admin(user_id):
        keyboard.add(Button("Админ-панель", "admins").inline())
    text_lines = []
    if active_account is not None:
        text_lines.append(
            "Игровой аккаунт: "
            f"<b>{formatting.escape_html(active_account.tag)}</b>"
        )
        if len(accounts) > 1:
            text_lines.append(f"Всего аккаунтов: {len(accounts)}")
        text_lines.append("")
    text_lines.append("Выберите раздел.")
    text = "\n".join(text_lines)
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def start(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id, _, _ = get_ids(message)
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    if show_unseen_releases(message, bot):
        return
    show_home_menu(message, bot)


def home(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id, _, _ = get_ids(message)
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    show_home_menu(message, bot)
