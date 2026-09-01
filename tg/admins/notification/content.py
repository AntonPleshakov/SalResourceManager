from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

from telebot import formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardMarkup

from logger.app_logger import logger
from resources.user_data import RESOURCE_FIELDS, ResourceField, UserData
from tg.utils import Button, format_user_identity, group_user_accounts


STANDARD_NOTIFICATION_TEXT = (
    "📢 <b>Сообщение от администратора</b>\n\n"
    "Пожалуйста, обновите ресурсы."
)
MAX_CUSTOM_TEXT_LENGTH = 3_000
MAX_TELEGRAM_MESSAGE_LENGTH = 4_096


class NotificationStates(StatesGroup):
    standard_confirmation = State()
    custom_text = State()
    custom_confirmation = State()


@dataclass(frozen=True)
class BroadcastResult:
    sent: int
    failed: int


@dataclass(frozen=True)
class StandardNotificationRecipient:
    user_id: int
    identity: str
    text: str
    keyboard: InlineKeyboardMarkup


@dataclass(frozen=True)
class StandardNotificationPlan:
    recipients: tuple[StandardNotificationRecipient, ...]
    skipped: int


def _update_keyboard(
    account_fields: Sequence[tuple[UserData, Sequence[ResourceField]]] = (),
    multiple_accounts: bool = False,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    if multiple_accounts:
        for index, (user, fields) in enumerate(account_fields, start=1):
            tag = str(user.tag.value).strip() or f"Аккаунт {index}"
            if fields:
                keyboard.add(
                    Button(
                        f"📦 Ресурсы · {tag}",
                        f"accounts/select/resources/{user.account_id.value}",
                    ).inline()
                )
        keyboard.add(Button("⬅️ Назад в меню", "home").inline())
        return keyboard

    keyboard.row(
        Button("📝 Обновить", "user_data/fill/resources").inline(),
        Button("🏠 В меню", "home").inline(),
    )
    return keyboard


def _standard_notification_text(fields: Iterable[ResourceField]) -> str:
    titles = "\n".join(f"• {field.title}" for field in fields)
    return (
        f"{STANDARD_NOTIFICATION_TEXT}\n\n"
        f"<b>Не обновлены сегодня:</b>\n{titles}"
    )


def _standard_notification_text_for_accounts(
    account_fields: Sequence[tuple[UserData, Sequence[ResourceField]]],
    multiple_accounts: bool,
) -> str:
    if not multiple_accounts:
        return _standard_notification_text(account_fields[0][1])

    blocks = []
    for index, (user, fields) in enumerate(account_fields, start=1):
        tag = str(user.tag.value).strip() or f"Аккаунт {index}"
        titles = "\n".join(f"• {field.title}" for field in fields)
        blocks.append(f"<b>{formatting.escape_html(tag)}</b>\n{titles}")
    return (
        f"{STANDARD_NOTIFICATION_TEXT}\n\n"
        "<b>Не обновлены сегодня:</b>\n\n"
        + "\n\n".join(blocks)
    )


def build_standard_notification_plan(
    users: Iterable[UserData], notification_date: date
) -> StandardNotificationPlan:
    recipients = []
    skipped = 0
    for user_id, accounts in group_user_accounts(users).items():
        account_fields = [
            (
                user,
                [
                    field
                    for field in RESOURCE_FIELDS
                    if user.get_updated_on(field.name) != notification_date
                ],
            )
            for user in accounts
        ]
        account_fields = [
            (user, fields) for user, fields in account_fields if fields
        ]
        if not account_fields:
            skipped += 1
            continue
        multiple_accounts = len(accounts) > 1
        recipients.append(
            StandardNotificationRecipient(
                user_id=user_id,
                identity=format_user_identity(
                    accounts[0].username.value, accounts[0].tag.value
                ),
                text=_standard_notification_text_for_accounts(
                    account_fields, multiple_accounts
                ),
                keyboard=_update_keyboard(account_fields, multiple_accounts),
            )
        )
    return StandardNotificationPlan(tuple(recipients), skipped)


def validate_custom_notification_text(text: str) -> str:
    clean_text = text.strip()
    if not clean_text:
        logger.warning("Rejected empty custom notification")
        raise ValueError("Notification text must not be empty")
    if len(clean_text) > MAX_CUSTOM_TEXT_LENGTH:
        logger.warning(
            "Rejected custom notification length=%d limit=%d",
            len(clean_text),
            MAX_CUSTOM_TEXT_LENGTH,
        )
        raise ValueError("Notification text is too long")
    return clean_text


def _user_mention(accounts: Sequence[UserData]) -> str:
    user = accounts[0]
    tags = list(
        dict.fromkeys(
            str(account.tag.value).strip()
            for account in accounts
            if str(account.tag.value).strip()
        )
    )
    name = format_user_identity(
        user.username.value or str(user.user_id.value), ", ".join(tags)
    )
    escaped_name = formatting.escape_html(name)
    return f'<a href="tg://user?id={user.user_id.value}">{escaped_name}</a>'


def custom_notification_header(text: str, admin_name: str) -> str:
    return (
        "📢 <b>Сообщение от администратора "
        f"{formatting.escape_html(admin_name)}</b>\n\n"
        f"{formatting.escape_html(text.strip())}"
    )


def build_custom_notification_messages(
    text: str,
    admin_name: str,
    users: Iterable[UserData],
) -> list[str]:
    header = custom_notification_header(
        validate_custom_notification_text(text), admin_name
    )
    mentions = [
        _user_mention(accounts)
        for accounts in group_user_accounts(users).values()
    ]
    if not mentions:
        return [header]

    prefix = "\n\n<b>Для всех участников:</b>\n"
    messages: list[str] = []
    current_mentions: list[str] = []
    for mention in mentions:
        candidate_mentions = current_mentions + [mention]
        candidate = header + prefix + ", ".join(candidate_mentions)
        if len(candidate) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            current_mentions = candidate_mentions
            continue
        if not current_mentions:
            raise ValueError("A user mention does not fit in a Telegram message")
        messages.append(header + prefix + ", ".join(current_mentions))
        current_mentions = [mention]

    messages.append(header + prefix + ", ".join(current_mentions))
    logger.debug(
        "Built custom notification chunks=%d recipients=%d",
        len(messages),
        len(mentions),
    )
    return messages
