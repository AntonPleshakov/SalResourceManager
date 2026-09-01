from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Iterable, Sequence

from telebot import formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardMarkup

from common.datetime_utils import week_started_on
from logger.app_logger import logger
from resources.user_data import UserData
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
    custom_audience = State()
    custom_confirmation = State()


class CustomNotificationAudience(str, Enum):
    ALL = "all"
    NOT_UPDATED_TODAY = "today"
    NOT_UPDATED_SINCE_MONDAY = "monday"


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
    accounts: Sequence[UserData] = (),
    multiple_accounts: bool = False,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    if multiple_accounts:
        for index, user in enumerate(accounts, start=1):
            tag = str(user.tag.value).strip() or f"Аккаунт {index}"
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


def _standard_notification_text() -> str:
    return (
        f"{STANDARD_NOTIFICATION_TEXT}\n\n"
        "Ресурсы не обновлялись с 03:00 понедельника."
    )


def _standard_notification_text_for_accounts(
    accounts: Sequence[UserData],
    multiple_accounts: bool,
) -> str:
    if not multiple_accounts:
        return _standard_notification_text()

    account_titles = []
    for index, user in enumerate(accounts, start=1):
        tag = str(user.tag.value).strip() or f"Аккаунт {index}"
        account_titles.append(f"• <b>{formatting.escape_html(tag)}</b>")
    return (
        f"{STANDARD_NOTIFICATION_TEXT}\n\n"
        "<b>Ресурсы не обновлялись с 03:00 понедельника:</b>\n"
        + "\n".join(account_titles)
    )


def build_standard_notification_plan(
    users: Iterable[UserData], cutoff: date
) -> StandardNotificationPlan:
    recipients = []
    skipped = 0
    for user_id, accounts in group_user_accounts(users).items():
        outdated_accounts = [
            user
            for user in accounts
            if not user.has_resource_updates_since(cutoff)
        ]
        if not outdated_accounts:
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
                    outdated_accounts, multiple_accounts
                ),
                keyboard=_update_keyboard(
                    outdated_accounts, multiple_accounts
                ),
            )
        )
    return StandardNotificationPlan(tuple(recipients), skipped)


def custom_notification_audience_title(
    audience: CustomNotificationAudience,
) -> str:
    return {
        CustomNotificationAudience.ALL: "все",
        CustomNotificationAudience.NOT_UPDATED_TODAY: (
            "не обновлявшие ресурсы сегодня"
        ),
        CustomNotificationAudience.NOT_UPDATED_SINCE_MONDAY: (
            "не обновлявшие ресурсы с 03:00 понедельника"
        ),
    }[audience]


def filter_custom_notification_users(
    users: Iterable[UserData],
    audience: CustomNotificationAudience,
    reference: datetime,
) -> tuple[UserData, ...]:
    users = tuple(users)
    if audience == CustomNotificationAudience.ALL:
        return users
    cutoff = (
        reference.date()
        if audience == CustomNotificationAudience.NOT_UPDATED_TODAY
        else week_started_on(reference)
    )
    return tuple(
        user
        for user in users
        if not user.has_resource_updates_since(cutoff)
    )


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
    recipient_title: str = "Для всех участников",
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

    prefix = f"\n\n<b>{formatting.escape_html(recipient_title)}:</b>\n"
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
