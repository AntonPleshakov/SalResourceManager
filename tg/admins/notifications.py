from telebot import TeleBot, formatting
from telebot.types import InlineKeyboardMarkup

from common.datetime_utils import now, week_started_on
from db.initializer import get_admins_db, get_user_data_db
from logger.app_logger import logger
from tg.admins.notification import (
    MAX_CUSTOM_TEXT_LENGTH,
    STANDARD_NOTIFICATION_TEXT,
    BroadcastResult,
    CustomNotificationAudience,
    NotificationStates,
    StandardNotificationPlan,
    build_custom_notification_messages,
    build_standard_notification_plan,
    custom_notification_audience_title,
    custom_notification_header,
    filter_custom_notification_users,
    validate_custom_notification_text,
)
from tg.admins.notification import delivery
from tg.admins.notification.handlers import register_handlers
from tg.admins.notification.views import notifications_menu
from tg.handlers import ClanAdminContext
from tg.utils import (
    Button,
    get_ids,
    get_username,
    group_user_accounts,
)


def send_standard_notification(
    bot: TeleBot, plan: StandardNotificationPlan
) -> BroadcastResult:
    return delivery.send_standard(bot, plan)


def send_custom_notification(
    bot: TeleBot,
    text: str,
    admin_name: str,
    group_id: int,
    audience: CustomNotificationAudience = CustomNotificationAudience.ALL,
) -> BroadcastResult:
    database = get_user_data_db()
    users = filter_custom_notification_users(
        database.get_clan_users(group_id), audience, now()
    )
    recipient_count = len(group_user_accounts(users))
    messages = build_custom_notification_messages(
        text,
        admin_name,
        users,
        recipient_title=(
            "Для всех участников"
            if audience == CustomNotificationAudience.ALL
            else f"Получатели — {custom_notification_audience_title(audience)}"
        ),
    )
    return delivery.send_group(bot, group_id, messages, recipient_count)


def send_custom_private_notification(
    bot: TeleBot,
    text: str,
    admin_name: str,
    group_id: int,
    audience: CustomNotificationAudience = CustomNotificationAudience.ALL,
) -> BroadcastResult:
    clean_text = validate_custom_notification_text(text)
    message = custom_notification_header(clean_text, admin_name)
    database = get_user_data_db()
    users = filter_custom_notification_users(
        database.get_clan_users(group_id), audience, now()
    )
    grouped_users = group_user_accounts(users)
    return delivery.send_private(bot, message, grouped_users)


def confirm_standard_notification(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    database = get_user_data_db()
    plan = build_standard_notification_plan(
        database.get_clan_users(context.group.group_id), week_started_on(now())
    )
    bot.set_state(user_id, NotificationStates.standard_confirmation)
    bot.add_data(
        user_id,
        standard_notification_plan=plan,
        admin_group_id=context.group.group_id,
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
        "Уведомление получат пользователи, которые не обновляли ни один "
        "ресурс с 03:00 понедельника.\n\n"
        f"Получателей: <b>{len(plan.recipients)}</b>\n"
        f"Уже обновили хотя бы один ресурс: <b>{plan.skipped}</b>",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def send_standard_notification_confirmed(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    logger.info(
        "Standard notification confirmed by admin_id=%s username=%s",
        callback_query.from_user.id,
        get_username(callback_query),
    )
    user_id = get_ids(callback_query)[0]
    with bot.retrieve_data(user_id) as data:
        plan = data.get("standard_notification_plan")
    group_id = context.group.group_id
    if not isinstance(plan, StandardNotificationPlan):
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось найти список получателей",
            show_alert=True,
        )
        notifications_menu(context)
        return

    chat_id, message_id = get_ids(callback_query)[1:]
    bot.edit_message_text(
        "Отправляю уведомления…",
        chat_id,
        message_id,
    )
    database = get_user_data_db()
    current_plan = build_standard_notification_plan(
        database.get_clan_users(group_id), week_started_on(now())
    )
    result = send_standard_notification(bot, current_plan)
    bot.answer_callback_query(
        callback_query.id,
        f"Доставлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(context)


def request_custom_notification(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.set_state(user_id, NotificationStates.custom_text)
    bot.add_data(user_id, admin_group_id=context.group.group_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("✖️ Отмена", "admins/notifications").inline())
    bot.edit_message_text(
        "Введите текст уведомления. После этого выберите получателей и способ "
        "отправки: в группу с упоминаниями или личным сообщением от бота.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def _custom_audience_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            "👥 Всем",
            "admins/notifications/custom_audience/all",
        ).inline(),
        Button(
            "📅 Не обновлявшим сегодня",
            "admins/notifications/custom_audience/today",
        ).inline(),
        Button(
            "🗓 Не обновлявшим с понедельника",
            "admins/notifications/custom_audience/monday",
        ).inline(),
        Button("✖️ Отмена", "admins/notifications").inline(),
    )
    return keyboard


def _custom_delivery_keyboard() -> InlineKeyboardMarkup:
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
    return keyboard


def receive_custom_notification_text(context: ClanAdminContext) -> None:
    message = context.update
    bot = context.bot
    user_id, chat_id = get_ids(message)[:2]
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

    logger.info(
        "Custom notification draft accepted admin_id=%s username=%s length=%d",
        user_id,
        get_username(message),
        len(text),
    )
    admin_name = get_username(message)
    bot.set_state(user_id, NotificationStates.custom_audience)
    bot.add_data(user_id, notification_text=text, admin_name=admin_name)
    preview = (
        "<b>Предпросмотр:</b>\n\n"
        f"{formatting.escape_html(text)}\n\n"
        "Кому отправить уведомление?"
    )
    bot.send_message(
        chat_id,
        preview,
        reply_markup=_custom_audience_keyboard(),
    )


def select_custom_notification_audience(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    try:
        audience = CustomNotificationAudience(
            callback_query.data.rsplit("/", 1)[-1]
        )
    except ValueError:
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось выбрать получателей",
            show_alert=True,
        )
        return

    bot.set_state(user_id, NotificationStates.custom_confirmation)
    bot.add_data(user_id, notification_audience=audience.value)
    with bot.retrieve_data(user_id) as data:
        text = data.get("notification_text", "")
    bot.edit_message_text(
        "<b>Предпросмотр:</b>\n\n"
        f"{formatting.escape_html(text)}\n\n"
        "Получатели: "
        f"<b>{custom_notification_audience_title(audience)}</b>.\n\n"
        "Выберите способ отправки.",
        chat_id,
        message_id,
        reply_markup=_custom_delivery_keyboard(),
    )


def _get_custom_notification_data(
    bot: TeleBot,
    user_id: int,
    group_id: int,
) -> tuple[str, str, CustomNotificationAudience, int]:
    with bot.retrieve_data(user_id) as data:
        return (
            data.get("notification_text", ""),
            data.get("admin_name", "Администратор"),
            CustomNotificationAudience(
                data.get(
                    "notification_audience",
                    CustomNotificationAudience.ALL.value,
                )
            ),
            group_id,
        )


def send_custom_group_notification_confirmed(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id = get_ids(callback_query)[0]
    text, admin_name, audience, group_id = _get_custom_notification_data(
        bot,
        user_id,
        context.group.group_id,
    )
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
        result = send_custom_notification(
            bot, text, admin_name, group_id, audience
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
    notifications_menu(context)


def send_custom_private_notification_confirmed(
    context: ClanAdminContext,
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id = get_ids(callback_query)[0]
    text, admin_name, audience, group_id = _get_custom_notification_data(
        bot,
        user_id,
        context.group.group_id,
    )
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
    result = send_custom_private_notification(
        bot, text, admin_name, group_id, audience
    )
    bot.answer_callback_query(
        callback_query.id,
        f"Доставлено: {result.sent}, ошибок: {result.failed}",
        show_alert=True,
    )
    notifications_menu(context)
