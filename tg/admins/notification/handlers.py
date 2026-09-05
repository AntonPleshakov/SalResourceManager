from telebot import TeleBot

from tg.admins.notification.content import NotificationStates
from tg.handlers import ActiveClan, ClanFromState, HandlerRegistry


def register_handlers(bot: TeleBot) -> None:
    from tg.admins.notifications import (
        confirm_standard_notification,
        notifications_menu,
        receive_custom_notification_text,
        request_custom_notification,
        select_custom_notification_audience,
        send_custom_group_notification_confirmed,
        send_custom_private_notification_confirmed,
        send_standard_notification_confirmed,
    )

    handlers = HandlerRegistry(bot)
    handlers.clan_admin_callback(
        notifications_menu,
        button="admins/notifications",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        confirm_standard_notification,
        button="admins/notifications/standard",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        send_standard_notification_confirmed,
        state=NotificationStates.standard_confirmation,
        button="admins/notifications/send_standard",
        clan=ClanFromState(),
    )
    handlers.clan_admin_callback(
        request_custom_notification,
        button="admins/notifications/custom",
        clan=ActiveClan(),
    )
    handlers.clan_admin_message(
        receive_custom_notification_text,
        content_types=["text"],
        state=NotificationStates.custom_text,
        clan=ClanFromState(),
    )
    handlers.clan_admin_callback(
        select_custom_notification_audience,
        state=NotificationStates.custom_audience,
        button=r"admins/notifications/custom_audience/(all|today|monday)",
        clan=ClanFromState(),
    )
    handlers.clan_admin_callback(
        send_custom_group_notification_confirmed,
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_group",
        clan=ClanFromState(),
    )
    handlers.clan_admin_callback(
        send_custom_private_notification_confirmed,
        state=NotificationStates.custom_confirmation,
        button="admins/notifications/send_custom_private",
        clan=ClanFromState(),
    )
