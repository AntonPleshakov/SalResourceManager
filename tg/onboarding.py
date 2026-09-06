from html import escape
from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from logger.app_logger import logger
from tg.rich import (
    button_row,
    callback_button,
    deliver_rich_message,
    heading,
    input_rich_message,
)
from tg.user_data.common import ensure_active_user
from tg.utils import get_ids, get_username


def show_created_account_welcome(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    user,
    group_tag_found: bool,
) -> None:
    user_id = get_ids(message)[0]
    account_name = escape(str(user.tag.value))
    action_rows = []

    if not group_tag_found:
        action_rows.append(
            button_row(
                (
                    callback_button(
                        "✏️ Переименовать аккаунт",
                        "accounts/rename",
                        style="primary",
                    ),
                )
            )
        )
        account_text = (
            "Не удалось получить ваш тег из группы, поэтому аккаунт временно "
            f"назван <b>{account_name}</b>. Переименуйте его перед заполнением "
            "данных."
        )
    else:
        account_text = (
            "По вашему тегу в группе создан игровой аккаунт "
            f"<b>{account_name}</b>."
        )
        action_rows.append(
            button_row(
                (
                    callback_button(
                        "📦 Заполнить ресурсы",
                        "resources",
                        style="primary",
                    ),
                )
            )
        )

    action_rows.append(
        button_row((callback_button("🏠 Открыть меню", "home"),))
    )
    deliver_rich_message(
        message,
        bot,
        input_rich_message(
            (
                heading("👋 Добро пожаловать!"),
                "<p>Бот помогает хранить ресурсы игровых аккаунтов, "
                "напоминает об обновлении данных и рассчитывает очки "
                "войны.</p>",
                f"<p>{account_text}</p>",
                *action_rows,
            )
        ),
    )
    logger.info(
        "New user onboarding shown to user_id=%s username=%s",
        user_id,
        get_username(message),
    )


def show_new_user_welcome(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    active_user = ensure_active_user(message, bot)
    if active_user.clan_selection_required:
        return True
    if not active_user.is_new_user:
        return False
    show_created_account_welcome(
        message,
        bot,
        active_user.user,
        bool(active_user.group_tag_found),
    )
    return True
