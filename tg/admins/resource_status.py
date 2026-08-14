from datetime import date
from typing import Iterable, List

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from common.datetime_utils import now
from db.initializer import get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from tg.utils import (
    Button,
    empty_filter,
    format_user_identity,
    get_ids,
    get_username,
)


MAX_TELEGRAM_MESSAGE_LENGTH = 4_096


def _days_word(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return "день"
    if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        return "дня"
    return "дней"


def _format_last_update(updated_on: date | None, reference_date: date) -> str:
    if updated_on is None:
        return "никогда"

    days_ago = (reference_date - updated_on).days
    formatted_date = updated_on.strftime("%d.%m.%Y")
    if days_ago < 0:
        return formatted_date
    if days_ago == 0:
        relative = "сегодня"
    elif days_ago == 1:
        relative = "вчера"
    else:
        relative = f"{days_ago} {_days_word(days_ago)} назад"
    return f"{relative} ({formatted_date})"


def _user_link(user: UserData) -> str:
    identity = format_user_identity(
        user.username.value or str(user.user_id.value), user.tag.value
    )
    return (
        f'<a href="tg://user?id={user.user_id.value}">'
        f"{formatting.escape_html(identity)}</a>"
    )


def build_last_updates_report(
    users: Iterable[UserData],
    reference_date: date,
) -> str:
    user_blocks = [
        f"• {_user_link(user)} — "
        f"{_format_last_update(user.get_last_updated_on(), reference_date)}"
        for user in users
    ]
    header = "<b>Последнее обновление аккаунтов</b>"
    if not user_blocks:
        return f"{header}\n\nАккаунтов пока нет."
    return f"{header}\n\n" + "\n\n".join(user_blocks)


def _split_report(report: str) -> List[str]:
    if len(report) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return [report]

    chunks: List[str] = []
    current = ""
    for block in report.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    return chunks


def last_updates(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    users = get_user_data_db().get_users()
    report = build_last_updates_report(users, now().date())
    chunks = _split_report(report)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())

    logger.info(
        "Last account updates requested by user_id=%s username=%s users=%d",
        user_id,
        get_username(callback_query),
        len(users),
    )
    bot.edit_message_text(
        chunks[0],
        chat_id,
        message_id,
        reply_markup=keyboard if len(chunks) == 1 else None,
    )
    for index, chunk in enumerate(chunks[1:], start=1):
        bot.send_message(
            chat_id,
            chunk,
            reply_markup=keyboard if index == len(chunks) - 1 else None,
        )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering last account updates handler")
    bot.register_callback_query_handler(
        last_updates,
        func=empty_filter,
        button="admins/last_updates",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
