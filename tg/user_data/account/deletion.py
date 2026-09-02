from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup

import tg.user_data as user_data
from tg.user_data.common import get_current_accounts
from tg.utils import Button, get_ids


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
    keyboard = InlineKeyboardMarkup(row_width=1)
    for account in candidates:
        keyboard.add(
            Button(
                f"🗑 {account.tag}",
                f"accounts/delete/confirm/{account.account_id}",
            ).inline()
        )
    keyboard.add(Button("✖️ Отмена", "accounts").inline())
    bot.edit_message_text(
        "<b>Удаление аккаунта</b>\n\n"
        "Выберите неактивный аккаунт, который нужно удалить.",
        chat_id,
        message_id,
        reply_markup=keyboard,
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
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            "🗑 Да, удалить вместе с данными",
            f"accounts/delete/{account.account_id}",
        ).inline()
    )
    keyboard.add(Button("✖️ Отмена", "accounts/delete").inline())
    bot.edit_message_text(
        f"Удалить аккаунт <b>{formatting.escape_html(account.tag)}</b>?\n\n"
        "Все сохранённые для него ресурсы и настройки будут удалены безвозвратно.",
        chat_id,
        message_id,
        reply_markup=keyboard,
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
