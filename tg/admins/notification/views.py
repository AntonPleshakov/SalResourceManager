from logger.app_logger import logger
from tg.handlers import ClanAdminContext
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    footer,
    heading,
    input_rich_message,
    notice as rich_notice,
)
from tg.utils import get_ids, get_username


def show_notifications_menu(
    context: ClanAdminContext, notice: str = ""
) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening notifications menu for admin_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    parts = []
    if notice:
        parts.append(rich_notice(notice))
    parts.extend(
        (
            heading("Уведомления пользователям"),
            footer(f"Клан: {context.group.title}"),
            "<p>Выберите готовое напоминание или напишите своё "
            "сообщение.</p>",
            button_row(
                (
                    callback_button(
                        "🔔 Напомнить обновить данные",
                        "admins/notifications/standard",
                        style="primary",
                    ),
                )
            ),
            button_row(
                (
                    callback_button(
                        "✍️ Написать сообщение",
                        "admins/notifications/custom",
                    ),
                )
            ),
            back_button("⬅️ Админ-панель", "admins"),
        )
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
    )


def notifications_menu(context: ClanAdminContext) -> None:
    show_notifications_menu(context)
