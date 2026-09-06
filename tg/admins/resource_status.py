from datetime import date
from typing import Iterable, List

from telebot import TeleBot, formatting
from common.datetime_utils import format_last_update
from db.initializer import get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from tg.handlers import ActiveClan, ClanAdminContext, HandlerRegistry
from tg.rich import (
    back_button,
    edit_rich_message,
    heading,
    highlight_metric,
    input_rich_message,
)
from tg.utils import (
    format_user_identity,
    get_ids,
    get_username,
)


MAX_RICH_MESSAGE_LENGTH = 30_000


def _format_last_update(updated_on: date | None) -> str:
    return format_last_update(updated_on)


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
) -> str:
    sorted_users = sorted(
        users,
        key=lambda user: user.get_last_resource_updated_on() or date.min,
        reverse=True,
    )
    user_blocks = [
        f"<p>{_user_link(user)}<br>"
        f"<i>{_format_last_update(user.get_last_resource_updated_on())}</i></p>"
        for user in sorted_users
    ]
    header = "".join(
        (
            heading("Последнее обновление ресурсов"),
            highlight_metric("Всего аккаунтов", str(len(sorted_users))),
        )
    )
    if not user_blocks:
        return f"{header}<p>Аккаунтов пока нет.</p>"
    return f"{header}\n\n" + "\n\n".join(user_blocks)


def _split_report(report: str) -> List[str]:
    if len(report) <= MAX_RICH_MESSAGE_LENGTH:
        return [report]

    chunks: List[str] = []
    current = ""
    for block in report.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= MAX_RICH_MESSAGE_LENGTH:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    return chunks


def last_updates(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    database = get_user_data_db()
    users = database.get_clan_users(context.group.group_id)
    report = build_last_updates_report(users)
    chunks = _split_report(report)
    back = back_button("⬅️ Админ-панель", "admins")

    logger.info(
        "Last account updates requested by user_id=%s username=%s users=%d",
        user_id,
        get_username(callback_query),
        len(users),
    )
    first_message = input_rich_message(
        (chunks[0], back if len(chunks) == 1 else "")
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        first_message,
    )
    for index, chunk in enumerate(chunks[1:], start=1):
        bot.send_rich_message(
            chat_id,
            input_rich_message(
                (chunk, back if index == len(chunks) - 1 else "")
            ),
        )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering last account updates handler")
    HandlerRegistry(bot).clan_admin_callback(
        last_updates,
        button="admins/last_updates",
        clan=ActiveClan(),
    )
