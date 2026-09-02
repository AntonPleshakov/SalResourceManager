from typing import Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.user_data.account.routing import DESTINATIONS, requested_destination
from tg.user_data.common import ensure_active_user, get_current_accounts
from tg.utils import Button, get_ids, get_username


def accounts_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id, chat_id, message_id = get_ids(message)
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
    lines = ["<b>Игровые аккаунты</b>"]
    if accounts:
        active_tag = (
            formatting.escape_html(active.tag)
            if active is not None
            else "не выбран"
        )
        clan_title = (
            formatting.escape_html(active.clan_title)
            if active is not None and active.clan_id is not None
            else "не выбран"
        )
        lines.extend(
            [
                "",
                f"Активный аккаунт: <b>{active_tag}</b>.",
                f"Клан: <b>{clan_title}</b>.",
            ]
        )
        if len(accounts) > 1:
            lines.extend(
                ["", "Выберите другой аккаунт, чтобы переключиться."]
            )
    else:
        lines.extend(
            [
                "",
                "Добавьте игровой аккаунт. Для каждого аккаунта ресурсы "
                "и очки учитываются отдельно.",
            ]
        )
    if notice:
        lines = [notice, "", *lines]

    keyboard = InlineKeyboardMarkup(row_width=1)
    for account in accounts:
        if account.is_active or (
            destination != "accounts" and account.clan_id is None
        ):
            continue
        clan_title = account.clan_title or "клан не выбран"
        keyboard.add(
            Button(
                f"🔄 {account.tag} · {clan_title}",
                f"accounts/select/{destination}/{account.account_id}",
            ).inline()
        )
    account_actions = [
        Button("➕ Добавить", f"accounts/add/{destination}").inline()
    ]
    if active is not None:
        account_actions.append(
            Button("✏️ Переименовать", "accounts/rename").inline()
        )
        target_clan_ids = available_clan_ids - {active.clan_id}
        if active.clan_id is None and target_clan_ids:
            account_actions.append(
                Button("🏰 Выбрать клан", "accounts/move").inline()
            )
        elif active.clan_id is not None and target_clan_ids:
            account_actions.append(
                Button("🏰 Сменить клан", "accounts/move").inline()
            )
        if active.clan_id is not None:
            account_actions.append(
                Button(
                    "🚪 Выйти из клана",
                    f"accounts/move/{active.account_id}/leave",
                ).inline()
            )
    keyboard.row(*account_actions)
    if len(accounts) > 1:
        keyboard.add(Button("🗑 Удалить аккаунт", "accounts/delete").inline())
    back_callback = destination if destination in DESTINATIONS else "home"
    keyboard.add(Button("⬅️ Назад", back_callback).inline())

    text = "\n".join(lines)
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
