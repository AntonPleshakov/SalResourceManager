from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from common.datetime_utils import now
from db.initializer import get_admins_db, get_user_data_db
from logger.app_logger import logger
from tg.admins.notification import (
    MAX_CUSTOM_TEXT_LENGTH,
    STANDARD_NOTIFICATION_TEXT,
    BroadcastResult,
    NotificationStates,
    StandardNotificationPlan,
    build_custom_notification_messages,
    build_standard_notification_plan,
    custom_notification_header,
    validate_custom_notification_text,
)
from tg.admins.notification import delivery
from tg.admins.notification.handlers import register_handlers
from tg.admins.notification.views import notifications_menu
from tg.admins.common import get_active_admin_group
from tg.utils import (
    Button,
    get_ids,
    get_username,
    group_user_accounts,
)


def send_standard_notification(
    bot: TeleBot, plan: StandardNotificationPlan | None = None
) -> BroadcastResult:
    if plan is None:
        plan = build_standard_notification_plan(
            get_user_data_db().get_users(), now().date()
        )

    return delivery.send_standard(bot, plan)


def send_custom_notification(
    bot: TeleBot,
    text: str,
    admin_name: str,
    group_id: int,
) -> BroadcastResult:
    users = get_user_data_db().get_users(group_id)
    recipient_count = len(group_user_accounts(users))
    messages = build_custom_notification_messages(text, admin_name, users)
    return delivery.send_group(bot, group_id, messages, recipient_count)


def send_custom_private_notification(
    bot: TeleBot,
    text: str,
    admin_name: str,
    group_id: int | None = None,
) -> BroadcastResult:
    clean_text = validate_custom_notification_text(text)
    message = custom_notification_header(clean_text, admin_name)
    users = get_user_data_db().get_users(group_id)
    grouped_users = group_user_accounts(users)
    return delivery.send_private(bot, message, grouped_users)


def confirm_standard_notification(
    callback_query: CallbackQuery, bot: TeleBot
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    group = get_active_admin_group(user_id)
    plan = build_standard_notification_plan(
        get_user_data_db().get_users(group.group_id), now().date()
    )
    bot.set_state(user_id, NotificationStates.standard_confirmation)
    bot.add_data(
        user_id,
        standard_notification_plan=plan,
        admin_group_id=group.group_id,
    )
    keyboard = InlineKeyboardMarkup()
    if plan.recipients:
        keyboard.row(
            Button(
                "📣 Отправить",
                "admins/notifications/send_standard",
            ).inline(),
            Button("✖️ Отмена", "admins/notifications").inline(),
        )
    else:
        keyboard.row(Button("⬅️ Назад", "admins/notifications").inline())
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
    user_id = get_ids(callback_query)[0]
    with bot.retrieve_data(user_id) as data:
        plan = data.get("standard_notification_plan")
        group_id = data.get("admin_group_id")
    if (
        not isinstance(plan, StandardNotificationPlan)
        or not isinstance(group_id, int)
        or not get_admins_db().is_admin(user_id, group_id)
    ):
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось найти список получателей",
            show_alert=True,
        )
        notifications_menu(callback_query, bot)
        return

    chat_id, message_id = get_ids(callback_query)[1:]
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
    keyboard.add(Button("✖️ Отмена", "admins/notifications").inline())
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

    user_id, chat_id = get_ids(message)[:2]
    logger.info(
        "Custom notification draft accepted admin_id=%s username=%s length=%d",
        user_id,
        get_username(message),
        len(text),
    )
    admin_name = get_username(message)
    bot.set_state(user_id, NotificationStates.custom_confirmation)
    bot.add_data(user_id, notification_text=text, admin_name=admin_name)
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button(
            "👥 В группу",
            "admins/notifications/send_custom_group",
        ).inline(),
        Button(
            "✉️ Лично",
            "admins/notifications/send_custom_private",
        ).inline(),
    )
    keyboard.row(Button("✖️ Отмена", "admins/notifications").inline())
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
    user_id = get_ids(callback_query)[0]
    text, admin_name = _get_custom_notification_data(bot, user_id)
    logger.info(
        "Custom group notification confirmed admin_id=%s username=%s length=%d",
        user_id,
        get_username(callback_query),
        len(text),
    )
    chat_id, message_id = get_ids(callback_query)[1:]
    bot.edit_message_text(
        "Отправляю уведомление в группу…",
        chat_id,
        message_id,
    )

    try:
        group = get_active_admin_group(user_id)
        result = send_custom_notification(
            bot, text, admin_name, group.group_id
        )
    except RuntimeError:
        logger.warning(
            "Custom group notification rejected: access group is not configured"
        )
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            Button("⬅️ Назад к уведомлениям", "admins/notifications").inline()
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
    user_id = get_ids(callback_query)[0]
    text, admin_name = _get_custom_notification_data(bot, user_id)
    logger.info(
        "Custom private notification confirmed admin_id=%s username=%s length=%d",
        user_id,
        get_username(callback_query),
        len(text),
    )
    chat_id, message_id = get_ids(callback_query)[1:]
    bot.edit_message_text(
        "Отправляю личные уведомления…",
        chat_id,
        message_id,
    )
    group = get_active_admin_group(user_id)
    result = send_custom_private_notification(
        bot, text, admin_name, group.group_id
    )
    bot.answer_callback_query(
        callback_query.id,
        f"Доставлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(callback_query, bot)
