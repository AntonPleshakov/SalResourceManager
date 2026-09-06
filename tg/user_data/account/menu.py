from typing import Union

from html import escape

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.user_data.account.routing import DESTINATIONS, requested_destination
from tg.user_data.common import ensure_active_user, get_current_accounts
from tg.rich import (
    account_context,
    back_button,
    button_row,
    callback_button,
    deliver_rich_message,
    heading,
    input_rich_message,
    notice as rich_notice,
)
from tg.utils import get_ids, get_username


def accounts_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id = get_ids(message)[0]
    bot.delete_state(user_id)
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(message, bot, database)
    if accounts is None:
        return
    database.update_username(user_id, get_username(message))
    if not accounts:
        active_user = ensure_active_user(message, bot)
        if active_user.user is None:
            return
        accounts = database.get_accounts(user_id)
    active = next((account for account in accounts if account.is_active), None)
    available_clan_ids = {
        group.group_id
        for group in get_user_clans(
            bot,
            user_id,
            user_data.get_access_group_db().get_groups(),
        )
    }
    destination = requested_destination(message)
    parts = []
    if notice:
        parts.append(rich_notice(notice))
    parts.append(heading("Игровые аккаунты"))
    if accounts:
        active_tag = (
            active.tag
            if active is not None
            else "не выбран"
        )
        clan_title = (
            active.clan_title
            if active is not None and active.clan_id is not None
            else "не выбран"
        )
        parts.append(account_context(active_tag, clan_title))
        if len(accounts) > 1:
            parts.append(
                "<p>Выберите другой аккаунт, чтобы переключиться.</p>"
            )
    else:
        parts.append(
            "<p>Добавьте игровой аккаунт. Для каждого аккаунта ресурсы "
            "и очки учитываются отдельно.</p>"
        )
    for account in accounts:
        if account.is_active or (
            destination != "accounts" and account.clan_id is None
        ):
            continue
        clan_title = account.clan_title or "клан не выбран"
        parts.extend(
            (
                f"<p><b>{escape(account.tag)}</b><br>"
                f"<i>{escape(clan_title)}</i></p>",
                button_row(
                    (
                        callback_button(
                            "Выбрать аккаунт",
                            f"accounts/select/{destination}/{account.account_id}",
                        ),
                    )
                ),
            )
        )
    account_actions = [callback_button("➕ Добавить", f"accounts/add/{destination}")]
    if active is not None:
        account_actions.append(
            callback_button("✏️ Переименовать", "accounts/rename")
        )
        target_clan_ids = available_clan_ids - {active.clan_id}
        if active.clan_id is None and target_clan_ids:
            account_actions.append(
                callback_button("🏰 Выбрать клан", "accounts/move")
            )
        elif active.clan_id is not None and target_clan_ids:
            account_actions.append(
                callback_button("🏰 Сменить клан", "accounts/move")
            )
        if active.clan_id is not None:
            account_actions.append(
                callback_button(
                    "🚪 Выйти из клана",
                    f"accounts/move/{active.account_id}/leave",
                )
            )
    for index in range(0, len(account_actions), 2):
        parts.append(button_row(account_actions[index : index + 2]))
    if len(accounts) > 1:
        parts.append(
            button_row(
                (
                    callback_button(
                        "🗑 Удалить аккаунт",
                        "accounts/delete",
                        style="danger",
                    ),
                )
            )
        )
    back_callback = destination if destination in DESTINATIONS else "home"
    back_text = (
        "⬅️ Главное меню" if back_callback == "home" else "⬅️ Назад"
    )
    parts.append(back_button(back_text, back_callback))
    deliver_rich_message(message, bot, input_rich_message(parts))
