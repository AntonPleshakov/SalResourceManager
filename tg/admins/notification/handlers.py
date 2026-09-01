from telebot import TeleBot

from tg.admins.notification.content import NotificationStates
from tg.utils import empty_filter


def register_handlers(bot: TeleBot) -> None:
    from tg.admins.notifications import (
        confirm_standard_notification,
        notifications_menu,
        receive_custom_notification_text,
        request_custom_notification,
        send_custom_group_notification_confirmed,
        send_custom_private_notification_confirmed,
        send_standard_notification_confirmed,
    )

    callback_defaults = {
        "func": empty_filter,
        "is_private": True,
        "is_admin": True,
        "pass_bot": True,
    }
    bot.register_callback_query_handler(
        notifications_menu,
        button="admins/notifications",
        **callback_defaults,
    )
    bot.register_callback_query_handler(
        confirm_standard_notification,
        button="admins/notifications/standard",
        **callback_defaults,
    )
    bot.register_callback_query_handler(
        send_standard_notification_confirmed,
        state=NotificationStates.standard_confirmation,
        button="admins/notifications/send_standard",
        **callback_defaults,
    )
    bot.register_callback_query_handler(
        request_custom_notification,
        button="admins/notifications/custom",
        **callback_defaults,
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
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_group",
        **callback_defaults,
    )
    bot.register_callback_query_handler(
        send_custom_private_notification_confirmed,
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_private",
        **callback_defaults,
    )
