from datetime import date, timedelta
from typing import Iterable, List

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from common.datetime_utils import now
from config.config import getconf_int
from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import TRACKED_FIELDS, UserData
from tg.utils import (
    Button,
    empty_filter,
    format_user_identity,
    get_ids,
    get_username,
)


MAX_TELEGRAM_MESSAGE_LENGTH = 4_096


def build_stale_resources_report(
    users: Iterable[UserData],
    reference_date: date,
    stale_after_days: int,
) -> str:
    if stale_after_days < 1:
        raise ValueError("Stale resource period must be at least one day")

    cutoff = reference_date - timedelta(days=stale_after_days)
    user_blocks = []
    for user in users:
        stale_fields = []
        for field in TRACKED_FIELDS:
            updated_on = user.get_updated_on(field.name)
            if updated_on is None or updated_on <= cutoff:
                updated_label = (
                    updated_on.strftime("%d.%m.%Y") if updated_on else "никогда"
                )
                stale_fields.append(f"• {field.title} — {updated_label}")

        if not stale_fields:
            continue
        identity = format_user_identity(
            user.username.value or str(user.user_id.value), user.tag.value
        )
        user_link = (
            f'<a href="tg://user?id={user.user_id.value}">'
            f"{formatting.escape_html(identity)}</a>"
        )
        user_blocks.append(f"{user_link}:\n" + "\n".join(stale_fields))

    header = f"<b>Данные без обновления {stale_after_days} дней и более</b>"
    if not user_blocks:
        return f"{header}\n\nВсе пользователи обновляют данные вовремя."
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


def stale_resources(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    stale_after_days = max(
        getconf_int("STALE_DATA_DAYS", getconf_int("STALE_RESOURCE_DAYS", 7)),
        1,
    )
    users = get_user_data_db().get_users()
    report = build_stale_resources_report(
        users,
        now().date(),
        stale_after_days,
    )
    chunks = _split_report(report)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад к администраторам", "admins").inline())

    logger.info(
        "Stale resource report requested by user_id=%s username=%s users=%d threshold_days=%d",
        user_id,
        get_username(callback_query),
        len(users),
        stale_after_days,
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
    logger.debug("Registering stale resource report handler")
    bot.register_callback_query_handler(
        stale_resources,
        func=empty_filter,
        button="admins/stale_resources",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
