from typing import Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
from tg.user_data.common import ensure_active_user
from tg.utils import Button, get_ids, get_username


def show_new_user_welcome(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    active_user = ensure_active_user(message, bot)
    if not active_user.is_new_user:
        return False

    user_id, chat_id, message_id = get_ids(message)
    account_name = formatting.escape_html(active_user.user.tag.value)
    keyboard = InlineKeyboardMarkup(row_width=1)

    if not active_user.group_tag_found:
        keyboard.add(
            Button("✏️ Переименовать аккаунт", "accounts/rename").inline()
        )
        account_text = (
            "Не удалось получить ваш тег из группы, поэтому аккаунт временно "
            f"назван <b>{account_name}</b>. Переименуйте его перед заполнением "
            "данных."
        )
    else:
        account_text = (
            "По вашему тегу в группе создан игровой аккаунт "
            f"<b>{account_name}</b>."
        )

    keyboard.add(Button("🏠 Открыть меню", "home").inline())
    text = (
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Бот помогает хранить ресурсы игровых аккаунтов, напоминает об "
        "обновлении данных и рассчитывает очки войны.\n\n"
        f"{account_text}"
    )
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
    logger.info(
        "New user onboarding shown to user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    return True
