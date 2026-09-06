from telebot import TeleBot
from telebot.types import CallbackQuery

import tg.user_data as user_data
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
    if not candidates:
        from tg.user_data.accounts import accounts_menu

        accounts_menu(callback_query, bot)
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
                        f"accounts/delete/confirm/{account.account_id}",
                    ),
                )
            )
        )
    parts.append(back_button("✖️ Отмена", "accounts"))
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
        account_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
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
                    f"accounts/delete/{account.account_id}",
                    "✖️ Отмена",
                    "accounts/delete",
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
        account_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
        if account_id not in {account.account_id for account in accounts}:
            raise ValueError("Игровой аккаунт не найден")
        database.delete_account(user_id, account_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return

    from tg.user_data.accounts import accounts_menu

    accounts_menu(callback_query, bot, "✅ Игровой аккаунт и его данные удалены.")
