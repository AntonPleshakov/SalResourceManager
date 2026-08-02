from dataclasses import dataclass
from typing import Iterable, List

from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from common.datetime_utils import now
from db.access_group import get_access_group_db
from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import TRACKED_FIELDS, ResourceField, UserData
from tg.utils import Button, empty_filter, get_ids, get_username


STANDARD_NOTIFICATION_TEXT = (
    "📢 <b>Сообщение от администратора</b>\n\n"
    "Пожалуйста, обновите все ресурсы и технологии."
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


def _update_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("Обновить ресурсы", "user_data/fill/resources").inline(),
        Button("Обновить технологии", "user_data/fill/technologies").inline(),
    )
    return keyboard


def _standard_notification_text(fields: Iterable[ResourceField]) -> str:
    titles = "\n".join(f"• {field.title}" for field in fields)
    return f"{STANDARD_NOTIFICATION_TEXT}\n\n<b>Не обновлены сегодня:</b>\n{titles}"


def send_standard_notification(bot: TeleBot) -> BroadcastResult:
    keyboard = _update_keyboard()
    sent = 0
    failed = 0
    skipped = 0
    users = get_user_data_db().get_users()
    notification_date = now().date()
    logger.info("Starting standard admin notification recipients=%d", len(users))
    for user in users:
        user_id = user.user_id.value
        missing_fields = [
            field
            for field in TRACKED_FIELDS
            if user.get_updated_on(field.name) != notification_date
        ]
        if not missing_fields:
            skipped += 1
            continue
        try:
            bot.send_message(
                user_id,
                _standard_notification_text(missing_fields),
                reply_markup=keyboard,
            )
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning(
                "Unable to send admin notification to user_id=%s username=%s: %s",
                user_id,
                user.username.value,
                error,
            )
    logger.info(
        "Standard admin notification sent=%s failed=%s skipped=%s",
        sent,
        failed,
        skipped,
    )
    return BroadcastResult(sent, failed)


def _user_mention(user: UserData) -> str:
    name = user.username.value or str(user.user_id.value)
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
    mentions = [_user_mention(user) for user in users]
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
    messages = build_custom_notification_messages(text, admin_name, users)
    logger.info(
        "Starting custom group notification recipients=%d chunks=%d",
        len(users),
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
    logger.info("Starting custom private notification recipients=%d", len(users))
    for user in users:
        user_id = user.user_id.value
        try:
            bot.send_message(user_id, message, disable_notification=False)
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning(
                "Unable to send custom private notification to user_id=%s username=%s: %s",
                user_id,
                user.username.value,
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
        Button("Назад к администраторам", "admins").inline(),
    )
    bot.edit_message_text(
        "Уведомления пользователям", chat_id, message_id, reply_markup=keyboard
    )


def confirm_standard_notification(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.set_state(user_id, NotificationStates.standard_confirmation)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("Отправить всем", "admins/notifications/send_standard").inline(),
        Button("Отмена", "admins/notifications").inline(),
    )
    bot.edit_message_text(
        f"<b>Будет отправлено:</b>\n\n{STANDARD_NOTIFICATION_TEXT}",
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
    result = send_standard_notification(bot)
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

    try:
        result = send_custom_notification(bot, text, admin_name)
    except RuntimeError:
        logger.warning(
            "Custom group notification rejected: access group is not configured"
        )
        bot.answer_callback_query(
            callback_query.id,
            "Группа не зарегистрирована",
            show_alert=True,
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
