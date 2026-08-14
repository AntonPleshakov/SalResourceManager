from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Sequence, Tuple

from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from common.datetime_utils import now
from db.initializer import get_access_group_db, get_user_data_db
from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    ResourceField,
    UserData,
)
from tg.utils import (
    Button,
    empty_filter,
    format_user_identity,
    get_ids,
    get_username,
    group_user_accounts,
)


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
    recipients: Tuple[StandardNotificationRecipient, ...]
    skipped: int


def _update_keyboard(
    account_fields: Sequence[Tuple[UserData, Sequence[ResourceField]]] = (),
    multiple_accounts: bool = False,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    if multiple_accounts:
        for index, (user, fields) in enumerate(account_fields, start=1):
            tag = str(user.tag.value).strip() or f"Аккаунт {index}"
            if fields:
                keyboard.add(
                    Button(
                        f"Ресурсы · {tag}",
                        f"accounts/select/resources/{user.account_id.value}",
                    ).inline()
                )
        keyboard.add(Button("Назад в меню", "home").inline())
        return keyboard

    keyboard.add(Button("Обновить ресурсы", "user_data/fill/resources").inline())
    return keyboard


def _standard_notification_text(fields: Iterable[ResourceField]) -> str:
    titles = "\n".join(f"• {field.title}" for field in fields)
    return f"{STANDARD_NOTIFICATION_TEXT}\n\n<b>Не обновлены сегодня:</b>\n{titles}"


def _standard_notification_text_for_accounts(
    account_fields: Sequence[Tuple[UserData, Sequence[ResourceField]]],
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
        f"{STANDARD_NOTIFICATION_TEXT}\n\n<b>Не обновлены сегодня:</b>\n\n"
        + "\n\n".join(blocks)
    )


def build_standard_notification_plan(
    users: Iterable[UserData], notification_date: date
) -> StandardNotificationPlan:
    recipients = []
    skipped = 0
    grouped_users = group_user_accounts(users)
    for user_id, accounts in grouped_users.items():
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


def send_standard_notification(
    bot: TeleBot, plan: StandardNotificationPlan | None = None
) -> BroadcastResult:
    if plan is None:
        plan = build_standard_notification_plan(
            get_user_data_db().get_users(), now().date()
        )

    sent = 0
    failed = 0
    logger.info(
        "Starting standard admin notification recipients=%d",
        len(plan.recipients),
    )
    for recipient in plan.recipients:
        try:
            bot.send_message(
                recipient.user_id,
                recipient.text,
                reply_markup=recipient.keyboard,
            )
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning(
                "Unable to send admin notification to user_id=%s username=%s: %s",
                recipient.user_id,
                recipient.identity,
                error,
            )
    logger.info(
        "Standard admin notification sent=%s failed=%s skipped=%s",
        sent,
        failed,
        plan.skipped,
    )
    return BroadcastResult(sent, failed)


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


def _custom_notification_header(text: str, admin_name: str) -> str:
    return (
        "📢 <b>Сообщение от администратора "
        f"{formatting.escape_html(admin_name)}</b>\n\n"
        f"{formatting.escape_html(text.strip())}"
    )


def build_custom_notification_messages(
    text: str,
    admin_name: str,
    users: Iterable[UserData],
) -> List[str]:
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

    header = _custom_notification_header(clean_text, admin_name)
    mentions = [
        _user_mention(accounts)
        for accounts in group_user_accounts(users).values()
    ]
    if not mentions:
        return [header]

    prefix = "\n\n<b>Для всех участников:</b>\n"
    messages: List[str] = []
    current_mentions: List[str] = []
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


def send_custom_notification(
    bot: TeleBot, text: str, admin_name: str
) -> BroadcastResult:
    group_id = get_access_group_db().get_group_id()
    if group_id is None:
        raise RuntimeError("Access group is not registered")

    users = get_user_data_db().get_users()
    recipient_count = len(group_user_accounts(users))
    messages = build_custom_notification_messages(text, admin_name, users)
    logger.info(
        "Starting custom group notification recipients=%d chunks=%d",
        recipient_count,
        len(messages),
    )
    sent = 0
    failed = 0
    for message in messages:
        try:
            # Telegram does not let bots override a user's notification settings.
            # Explicit group mentions provide the same behavior as a regular tag.
            bot.send_message(group_id, message, disable_notification=False)
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning("Unable to send custom admin notification: %s", error)
    logger.info("Custom admin notification sent=%s failed=%s", sent, failed)
    return BroadcastResult(sent, failed)


def send_custom_private_notification(
    bot: TeleBot, text: str, admin_name: str
) -> BroadcastResult:
    clean_text = text.strip()
    if not clean_text:
        logger.warning("Rejected empty custom private notification")
        raise ValueError("Notification text must not be empty")
    if len(clean_text) > MAX_CUSTOM_TEXT_LENGTH:
        logger.warning(
            "Rejected custom private notification length=%d limit=%d",
            len(clean_text),
            MAX_CUSTOM_TEXT_LENGTH,
        )
        raise ValueError("Notification text is too long")

    message = _custom_notification_header(clean_text, admin_name)
    sent = 0
    failed = 0
    users = get_user_data_db().get_users()
    grouped_users = group_user_accounts(users)
    logger.info(
        "Starting custom private notification recipients=%d", len(grouped_users)
    )
    for user_id, accounts in grouped_users.items():
        try:
            bot.send_message(user_id, message, disable_notification=False)
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning(
                "Unable to send custom private notification to user_id=%s username=%s: %s",
                user_id,
                format_user_identity(
                    accounts[0].username.value, accounts[0].tag.value
                ),
                error,
            )
    logger.info("Custom private notification sent=%s failed=%s", sent, failed)
    return BroadcastResult(sent, failed)


def notifications_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening notifications menu for admin_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            "Попросить обновить данные", "admins/notifications/standard"
        ).inline(),
        Button("Отправить свой текст", "admins/notifications/custom").inline(),
        Button("Назад в админ-панель", "admins").inline(),
    )
    bot.edit_message_text(
        "Уведомления пользователям", chat_id, message_id, reply_markup=keyboard
    )


def confirm_standard_notification(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    plan = build_standard_notification_plan(
        get_user_data_db().get_users(), now().date()
    )
    bot.set_state(user_id, NotificationStates.standard_confirmation)
    bot.add_data(user_id, standard_notification_plan=plan)
    keyboard = InlineKeyboardMarkup(row_width=1)
    if plan.recipients:
        keyboard.add(
            Button(
                "Отправить уведомление",
                "admins/notifications/send_standard",
            ).inline()
        )
    keyboard.add(Button("Отмена", "admins/notifications").inline())
    bot.edit_message_text(
        "<b>Попросить обновить данные?</b>\n\n"
        "Уведомление получат пользователи, у которых не все данные "
        "обновлены сегодня.\n\n"
        f"Получателей: <b>{len(plan.recipients)}</b>\n"
        f"Уже обновили данные: <b>{plan.skipped}</b>",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def send_standard_notification_confirmed(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    logger.info(
        "Standard notification confirmed by admin_id=%s username=%s",
        callback_query.from_user.id,
        get_username(callback_query),
    )
    user_id, _, _ = get_ids(callback_query)
    with bot.retrieve_data(user_id) as data:
        plan = data.get("standard_notification_plan")
    if not isinstance(plan, StandardNotificationPlan):
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось найти список получателей",
            show_alert=True,
        )
        notifications_menu(callback_query, bot)
        return

    _, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        "Отправляю уведомления…",
        chat_id,
        message_id,
    )
    result = send_standard_notification(bot, plan)
    bot.answer_callback_query(
        callback_query.id,
        f"Доставлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(callback_query, bot)


def request_custom_notification(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.set_state(user_id, NotificationStates.custom_text)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Отмена", "admins/notifications").inline())
    bot.edit_message_text(
        "Введите текст уведомления. После этого можно будет выбрать отправку "
        "в группу с упоминаниями или личным сообщением от бота.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def receive_custom_notification_text(message: Message, bot: TeleBot) -> None:
    text = (message.text or "").strip()
    if not text:
        logger.info(
            "Empty custom notification submitted by admin_id=%s username=%s",
            message.from_user.id,
            get_username(message),
        )
        bot.reply_to(message, "Текст уведомления не должен быть пустым.")
        return
    if len(text) > MAX_CUSTOM_TEXT_LENGTH:
        logger.info(
            "Oversized custom notification submitted by admin_id=%s username=%s length=%d",
            message.from_user.id,
            get_username(message),
            len(text),
        )
        bot.reply_to(
            message,
            f"Текст слишком длинный. Максимум — {MAX_CUSTOM_TEXT_LENGTH} символов.",
        )
        return

    user_id, chat_id, _ = get_ids(message)
    logger.info(
        "Custom notification draft accepted admin_id=%s username=%s length=%d",
        user_id,
        get_username(message),
        len(text),
    )
    admin_name = get_username(message)
    bot.set_state(user_id, NotificationStates.custom_confirmation)
    bot.add_data(user_id, notification_text=text, admin_name=admin_name)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            "В группу с тегами",
            "admins/notifications/send_custom_group",
        ).inline(),
        Button(
            "Лично от бота (может быть muted)",
            "admins/notifications/send_custom_private",
        ).inline(),
        Button("Отмена", "admins/notifications").inline(),
    )
    preview = (
        "<b>Предпросмотр:</b>\n\n"
        f"{formatting.escape_html(text)}\n\n"
        "Выберите способ отправки."
    )
    bot.send_message(chat_id, preview, reply_markup=keyboard)


def _get_custom_notification_data(bot: TeleBot, user_id: int) -> tuple[str, str]:
    with bot.retrieve_data(user_id) as data:
        return (
            data.get("notification_text", ""),
            data.get("admin_name", "Администратор"),
        )


def send_custom_group_notification_confirmed(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, _, _ = get_ids(callback_query)
    text, admin_name = _get_custom_notification_data(bot, user_id)
    logger.info(
        "Custom group notification confirmed admin_id=%s username=%s length=%d",
        user_id,
        get_username(callback_query),
        len(text),
    )
    _, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        "Отправляю уведомление в группу…",
        chat_id,
        message_id,
    )

    try:
        result = send_custom_notification(bot, text, admin_name)
    except RuntimeError:
        logger.warning(
            "Custom group notification rejected: access group is not configured"
        )
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            Button("Назад к уведомлениям", "admins/notifications").inline()
        )
        bot.edit_message_text(
            "Не удалось отправить уведомление: группа не зарегистрирована.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    bot.answer_callback_query(
        callback_query.id,
        f"Сообщений отправлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(callback_query, bot)


def send_custom_private_notification_confirmed(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, _, _ = get_ids(callback_query)
    text, admin_name = _get_custom_notification_data(bot, user_id)
    logger.info(
        "Custom private notification confirmed admin_id=%s username=%s length=%d",
        user_id,
        get_username(callback_query),
        len(text),
    )
    _, chat_id, message_id = get_ids(callback_query)
    bot.edit_message_text(
        "Отправляю личные уведомления…",
        chat_id,
        message_id,
    )
    result = send_custom_private_notification(bot, text, admin_name)
    bot.answer_callback_query(
        callback_query.id,
        f"Доставлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(callback_query, bot)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering notification handlers")
    bot.register_callback_query_handler(
        notifications_menu,
        func=empty_filter,
        button="admins/notifications",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        confirm_standard_notification,
        func=empty_filter,
        button="admins/notifications/standard",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        send_standard_notification_confirmed,
        func=empty_filter,
        state=NotificationStates.standard_confirmation,
        button="admins/notifications/send_standard",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        request_custom_notification,
        func=empty_filter,
        button="admins/notifications/custom",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        receive_custom_notification_text,
        content_types=["text"],
        chat_types=["private"],
        state=NotificationStates.custom_text,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        send_custom_group_notification_confirmed,
        func=empty_filter,
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_group",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        send_custom_private_notification_confirmed,
        func=empty_filter,
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_private",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
