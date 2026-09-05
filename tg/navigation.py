from html import escape
from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from db.initializer import get_admins_db, get_user_data_db
from logger.app_logger import logger
from tg.onboarding import show_new_user_welcome
from tg.releases import mark_current_release_seen, show_unseen_releases
from tg.rich import (
    button_row,
    callback_button,
    deliver_rich_message,
    input_rich_message,
)
from tg.utils import get_ids, get_username


def _show_onboarding(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    if not show_new_user_welcome(message, bot):
        return False
    mark_current_release_seen(message)
    return True


def show_home_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> None:
    user_id = get_ids(message)[0]
    database = get_user_data_db()
    accounts = database.get_accounts(user_id)
    active_account = next(
        (account for account in accounts if account.is_active),
        None,
    )
    reminders_enabled = database.reminders_enabled(user_id)
    logger.debug(
        "Opening home menu for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    parts = ["<h2>Главное меню</h2>"]
    if active_account is not None:
        account_rows = [
            "<tr><td>Игровой аккаунт</td>"
            f"<td><b>{escape(active_account.tag)}</b></td></tr>"
        ]
        if active_account.clan_title:
            account_rows.append(
                "<tr><td>Клан</td>"
                f"<td><b>{escape(active_account.clan_title)}</b></td></tr>"
            )
        if len(accounts) > 1:
            account_rows.append(
                "<tr><td>Всего аккаунтов</td>"
                f'<td align="right"><b>{len(accounts)}</b></td></tr>'
            )
        parts.extend(
            (
                '<table compact><caption>Текущий выбор</caption>',
                *account_rows,
                "</table>",
            )
        )
    parts.extend(
        (
            "<p>Выберите раздел.</p>",
            button_row(
                (
                    callback_button("🎮 Игровые аккаунты", "accounts"),
                )
            ),
            button_row(
                (
                    callback_button("📦 Ресурсы", "resources"),
                    callback_button("🔬 Технологии", "technologies"),
                )
            ),
            button_row(
                (
                    callback_button("🐾 Питомцы", "pets"),
                    callback_button(
                        "⚔️ Очки войны", "war_menu", style="primary"
                    ),
                )
            ),
            button_row(
                (
                    callback_button(
                        "🔕 Выключить напоминания"
                        if reminders_enabled
                        else "🔔 Включить напоминания",
                        "reminders/toggle",
                    ),
                )
            ),
            button_row((callback_button("🆕 Что нового", "releases"),)),
        )
    )
    if get_admins_db().has_admin_access(user_id):
        parts.append(
            button_row((callback_button("🛠 Админ-панель", "admins"),))
        )
    parts.append(
        "<details><summary>О напоминаниях</summary>"
        "<p>Настройка влияет только на автоматическое уведомление по "
        "понедельникам и не отключает сообщения администраторов.</p>"
        "<p>Не выключайте уведомления от бота в Telegram, чтобы не "
        "пропустить сообщения администраторов.</p></details>"
    )
    deliver_rich_message(message, bot, input_rich_message(parts))


def start(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    if show_unseen_releases(message, bot):
        return
    show_home_menu(message, bot)


def home(message: Union[Message, CallbackQuery], bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    bot.delete_state(user_id)
    if _show_onboarding(message, bot):
        return
    show_home_menu(message, bot)


def toggle_reminders(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = get_ids(callback_query)[0]
    database = get_user_data_db()
    enabled = not database.reminders_enabled(user_id)
    database.set_reminders_enabled(user_id, enabled)
    logger.info(
        "Monday resource reminders toggled enabled=%s for user_id=%s username=%s",
        enabled,
        user_id,
        get_username(callback_query),
    )
    show_home_menu(callback_query, bot)
