from html import escape
import sqlite3
from uuid import uuid4

from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import (
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from db.initializer import get_user_data_db
from resources.technology_badges import matches_technology_filter
from resources.user_data import UserData
from tg.admins.common import AdminAccessError, require_admin_access
from tg.admins.notification.content import (
    custom_notification_header,
    validate_custom_notification_text,
)
from tg.admins.notification.delivery import send_private
from tg.handlers import (
    ClanAdminContext,
    ClanFromCallback,
    ClanFromState,
    HandlerRegistry,
)
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    heading,
    input_rich_message,
)
from tg.utils import get_ids, group_user_accounts


TECHNOLOGY_FILTERS = {
    "any": "Без фильтра",
    "skills": "🎟️ Максимальные технологии навыков",
    "mounts": "🐎 Максимальные технологии маунтов",
    "pets": "🥚 Максимальные технологии петов",
    "all": "🏆 Все перечисленные технологии максимальны",
}
FILTER_PATTERN = "any|skills|mounts|pets|all"


class TopMessageStates(StatesGroup):
    text = State()
    confirmation = State()


def can_manage_top(bot: TeleBot, user_id: int, clan_id: int) -> bool:
    try:
        require_admin_access(bot, user_id, clan_id)
    except (AdminAccessError, RuntimeError, sqlite3.Error):
        return False
    return True


def filtered_top_users(
    clan_id: int,
    technology: str,
    account_ids: set[int] | None = None,
) -> list[UserData]:
    if technology not in TECHNOLOGY_FILTERS:
        raise ValueError("Неизвестный фильтр технологий")
    return [
        user
        for user in get_user_data_db().get_clan_users(clan_id)
        if matches_technology_filter(user, technology)
        and (account_ids is None or user.account_id.value in account_ids)
    ]


def top_filters(callback_query: CallbackQuery, bot: TeleBot) -> None:
    bot.delete_state(callback_query.from_user.id)
    current = callback_query.data.split("/")[-1]
    parts = [
        heading("Фильтр топа игроков"),
        "<p>Выберите максимальные технологии.</p>",
    ]
    for key, title in TECHNOLOGY_FILTERS.items():
        parts.append(button_row((
            callback_button(
                ("✅ " if key == current else "") + title,
                f"war_top/{key}/0",
            ),
        )))
    parts.append(back_button("⬅️ К топу", f"war_top/{current}/0"))
    edit_rich_message(bot, *get_ids(callback_query)[1:], input_rich_message(parts))


def copy_top_tags(context: ClanAdminContext) -> None:
    technology = context.update.data.split("/")[-1]
    users = filtered_top_users(context.group.group_id, technology)
    tags = list(dict.fromkeys(
        str(user.tag.value).strip()
        for user in users
        if str(user.tag.value).strip()
    ))
    if not tags:
        context.bot.answer_callback_query(
            context.update.id, "В списке нет заполненных тегов", show_alert=True,
        )
        return
    # Telegram copy buttons accept up to 256 characters. Preserve every tag.
    text = "\n".join(tags)
    chunks = []
    while text:
        end = min(256, len(text))
        if end < len(text):
            last_line = text.rfind("\n", 0, end + 1)
            if last_line > 0:
                end = last_line
        chunks.append(text[:end])
        text = text[end:].lstrip("\n")
    context.bot.answer_callback_query(context.update.id)
    for index, chunk in enumerate(chunks, start=1):
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(InlineKeyboardButton(
            f"📋 Скопировать теги ({index}/{len(chunks)})",
            copy_text=CopyTextButton(chunk),
        ))
        context.bot.send_message(
            context.chat_id, f"<pre>{escape(chunk)}</pre>", reply_markup=keyboard,
        )


def request_top_message(context: ClanAdminContext) -> None:
    technology = context.update.data.split("/")[-1]
    users = filtered_top_users(context.group.group_id, technology)
    if not users:
        context.bot.answer_callback_query(
            context.update.id, "Список получателей пуст", show_alert=True,
        )
        return
    context.bot.set_state(context.user_id, TopMessageStates.text)
    context.bot.add_data(
        context.user_id,
        top_clan_id=context.group.group_id,
        top_filter=technology,
        top_accounts=[user.account_id.value for user in users],
        top_draft=None,
    )
    parts = (
        heading("Сообщение игрокам из списка"),
        f"<p>Фильтр: {escape(TECHNOLOGY_FILTERS[technology])}. "
        f"Получателей: {len(group_user_accounts(users))}.</p>",
        "<p>Введите текст до 3000 символов. Затем подтвердите отправку личных сообщений.</p>",
        back_button("✖️ Отмена", f"war_top/{technology}/0"),
    )
    edit_rich_message(
        context.bot, context.chat_id, context.message_id, input_rich_message(parts),
    )


def receive_top_message(context: ClanAdminContext) -> None:
    try:
        text = validate_custom_notification_text(context.update.text or "")
    except ValueError:
        context.bot.send_message(
            context.chat_id, "Введите непустой текст до 3000 символов.",
        )
        return
    with context.bot.retrieve_data(context.user_id) as data:
        technology = data["top_filter"]
        account_ids = set(data["top_accounts"])
    users = filtered_top_users(context.group.group_id, technology, account_ids)
    token = uuid4().hex[:12]
    context.bot.add_data(context.user_id, top_draft=(token, text, context.username))
    context.bot.set_state(context.user_id, TopMessageStates.confirmation)
    parts = (
        heading("Предпросмотр сообщения"),
        f"<p>Клан: {escape(context.group.title)}. "
        f"Фильтр: {escape(TECHNOLOGY_FILTERS[technology])}. "
        f"Получателей: {len(group_user_accounts(users))}.</p>",
        f"<blockquote>{escape(text)}</blockquote>",
        button_row((callback_button("✉️ Отправить лично", f"war_top_send/{token}"),)),
        back_button("✖️ Отмена", f"war_top/{technology}/0"),
    )
    context.bot.send_rich_message(context.chat_id, input_rich_message(parts))


def send_top_message(context: ClanAdminContext) -> None:
    token = context.update.data.split("/")[-1]
    with context.bot.retrieve_data(context.user_id) as data:
        draft = data.get("top_draft")
        if not draft or draft[0] != token:
            context.bot.answer_callback_query(
                context.update.id,
                "Сообщение уже отправлено или устарело",
                show_alert=True,
            )
            return
        data.pop("top_draft")
        technology = data["top_filter"]
        account_ids = set(data["top_accounts"])
    context.bot.delete_state(context.user_id)
    context.bot.answer_callback_query(context.update.id, "Отправляю сообщения…")
    users = filtered_top_users(context.group.group_id, technology, account_ids)
    result = send_private(
        context.bot,
        custom_notification_header(draft[1], draft[2]),
        group_user_accounts(users),
    )
    parts = (
        heading("Отправка завершена"),
        f"<p>Доставлено: {result.sent}. Ошибок: {result.failed}.</p>",
        back_button("⬅️ К топу", f"war_top/{technology}/0"),
    )
    edit_rich_message(
        context.bot, context.chat_id, context.message_id, input_rich_message(parts),
    )


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.private_callback(
        top_filters, button=rf"war_top_filters/({FILTER_PATTERN})",
    )
    handlers.clan_admin_callback(
        copy_top_tags,
        button=rf"war_top_copy/-?[0-9]+/({FILTER_PATTERN})",
        clan=ClanFromCallback(1),
    )
    handlers.clan_admin_callback(
        request_top_message,
        button=rf"war_top_message/-?[0-9]+/({FILTER_PATTERN})",
        clan=ClanFromCallback(1),
    )
    handlers.clan_admin_message(
        receive_top_message,
        content_types=["text"],
        state=TopMessageStates.text,
        clan=ClanFromState("top_clan_id"),
    )
    handlers.clan_admin_callback(
        send_top_message,
        button=r"war_top_send/[0-9a-f]{12}",
        state=TopMessageStates.confirmation,
        clan=ClanFromState("top_clan_id"),
    )
