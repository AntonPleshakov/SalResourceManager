from telebot import TeleBot
from telebot.types import CallbackQuery

import tg.user_data as user_data
from tg.user_data.account.routing import DESTINATIONS, open_destination
from tg.user_data.common import get_current_accounts
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    confirmation_buttons,
    edit_rich_message,
    heading,
    input_rich_message,
    notice,
)
from tg.utils import get_ids


def request_delete(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    accounts = get_current_accounts(callback_query, bot)
    if accounts is None:
        return
    candidates = [account for account in accounts if not account.is_active]
    destination = callback_query.data.rsplit("/", maxsplit=1)[-1]
    if destination not in DESTINATIONS | {"accounts"}:
        destination = "accounts"
    if not candidates:
        open_destination(callback_query, bot, destination)
        return
    parts = [
        heading("Удаление аккаунта"),
        "<p>Выберите неактивный аккаунт. Активный аккаунт удалить "
        "нельзя.</p>",
    ]
    for account in candidates:
        parts.append(
            button_row(
                (
                    callback_button(
                        f"🗑 {account.tag}",
                        f"accounts/delete/confirm/{account.account_id}/"
                        f"{destination}",
                    ),
                )
            )
        )
    cancel_callback = (
        f"accounts/{destination}" if destination != "accounts" else "accounts"
    )
    parts.append(back_button("✖️ Отмена", cancel_callback))
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
    )


def confirm_delete(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    accounts = get_current_accounts(callback_query, bot)
    if accounts is None:
        return
    try:
        parts = callback_query.data.split("/")
        account_id = int(parts[3])
        destination = parts[4]
        if destination not in DESTINATIONS | {"accounts"}:
            raise ValueError("Раздел возврата не найден")
        account = next(
            account
            for account in accounts
            if account.account_id == account_id
        )
        if account.is_active:
            raise ValueError("Активный аккаунт нельзя удалить")
    except (StopIteration, TypeError, ValueError) as error:
        text = str(error) or "Игровой аккаунт не найден"
        bot.answer_callback_query(callback_query.id, text, show_alert=True)
        return
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(
            (
                heading(f"Удалить аккаунт «{account.tag}»?"),
                notice(
                    "Все сохранённые ресурсы и настройки аккаунта будут "
                    "удалены безвозвратно."
                ),
                confirmation_buttons(
                    "🗑 Удалить аккаунт и данные",
                    f"accounts/delete/{account.account_id}/{destination}",
                    "✖️ Отмена",
                    f"accounts/delete/menu/{destination}",
                    destructive=True,
                ),
            )
        ),
    )


def delete_account(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = get_ids(callback_query)[0]
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(callback_query, bot, database)
    if accounts is None:
        return
    try:
        parts = callback_query.data.split("/")
        account_id = int(parts[2])
        destination = parts[3]
        if destination not in DESTINATIONS | {"accounts"}:
            raise ValueError("Раздел возврата не найден")
        if account_id not in {account.account_id for account in accounts}:
            raise ValueError("Игровой аккаунт не найден")
        database.delete_account(user_id, account_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return

    open_destination(
        callback_query,
        bot,
        destination,
        "✅ Игровой аккаунт и его данные удалены.",
    )
