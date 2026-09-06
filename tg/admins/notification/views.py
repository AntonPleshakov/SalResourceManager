from logger.app_logger import logger
from tg.handlers import ClanAdminContext
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    heading,
    input_rich_message,
)
from tg.utils import get_ids, get_username


def notifications_menu(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening notifications menu for admin_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(
            (
                heading("Уведомления пользователям"),
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
        ),
    )
