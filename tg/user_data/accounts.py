from typing import Union

from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
import tg.user_data as user_data
from tg.utils import Button, empty_filter, get_ids, get_username


class GameAccountStates(StatesGroup):
    nickname = State()


DESTINATIONS = {"resources", "technologies", "pets", "war_calculator"}


def _requested_destination(message: Union[Message, CallbackQuery]) -> str:
    if not isinstance(message, CallbackQuery):
        return "accounts"
    candidate = message.data.split("/")[-1]
    return candidate if candidate in DESTINATIONS else "accounts"


def _open_destination(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    destination: str,
    notice: str = "",
) -> None:
    if destination == "resources":
        user_data.resources_menu(message, bot, notice)
    elif destination == "technologies":
        user_data.technologies_menu(message, bot, notice)
    elif destination == "pets":
        user_data.pets_menu(message, bot, notice)
    elif destination == "war_calculator":
        from tg.war.personal import personal_war_points

        personal_war_points(message, bot)
    else:
        accounts_menu(message, bot, notice)


def accounts_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    bot.delete_state(user_id)
    database = user_data.get_user_data_db()
    database.update_username(user_id, get_username(message))
    accounts = database.get_accounts(user_id)
    active = next((account for account in accounts if account.is_active), None)
    destination = _requested_destination(message)
    lines = ["<b>Игровые аккаунты</b>"]
    if accounts:
        active_tag = (
            formatting.escape_html(active.tag) if active is not None else "не выбран"
        )
        lines.extend(["", f"Активный аккаунт: <b>{active_tag}</b>."])
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
        if account.is_active:
            continue
        keyboard.add(
            Button(
                account.tag,
                f"accounts/select/{destination}/{account.account_id}",
            ).inline()
        )
    keyboard.add(
        Button("➕ Добавить аккаунт", f"accounts/add/{destination}").inline()
    )
    if active is not None:
        keyboard.add(Button("✏️ Переименовать аккаунт", "accounts/rename").inline())
    if len(accounts) > 1:
        keyboard.add(Button("🗑 Удалить аккаунт", "accounts/delete").inline())
    back_callback = destination if destination in DESTINATIONS else "home"
    keyboard.add(Button("Назад", back_callback).inline())

    text = "\n".join(lines)
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def _request_nickname(
    callback_query: CallbackQuery, bot: TeleBot, action: str
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    account = user_data.get_user_data_db().get_active_account(user_id)
    if action == "rename" and account is None:
        accounts_menu(callback_query, bot)
        return
    bot.set_state(user_id, GameAccountStates.nickname)
    bot.add_data(
        user_id,
        account_action=action,
        account_id=None if account is None else account.account_id,
        account_destination=_requested_destination(callback_query),
    )
    if action == "add":
        text = "Введите имя нового игрового аккаунта."
    else:
        text = (
            f"Введите новое имя для аккаунта "
            f"«{formatting.escape_html(account.tag)}»."
        )
    keyboard = InlineKeyboardMarkup(row_width=1)
    destination = _requested_destination(callback_query)
    cancel_callback = (
        f"accounts/{destination}" if destination in DESTINATIONS else "accounts"
    )
    keyboard.add(Button("Отмена", cancel_callback).inline())
    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)


def request_add(callback_query: CallbackQuery, bot: TeleBot) -> None:
    _request_nickname(callback_query, bot, "add")


def request_rename(callback_query: CallbackQuery, bot: TeleBot) -> None:
    _request_nickname(callback_query, bot, "rename")


def save_nickname(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    with bot.retrieve_data(user_id) as data:
        action = data.get("account_action")
        account_id = data.get("account_id")
        destination = data.get("account_destination")
    try:
        if action == "add":
            account = user_data.get_user_data_db().add_account(
                user_id, get_username(message), message.text
            )
            notice = (
                f"✅ Аккаунт «{formatting.escape_html(account.tag)}» добавлен и выбран."
            )
        elif action == "rename" and isinstance(account_id, int):
            account = user_data.get_user_data_db().rename_account(
                user_id, account_id, message.text
            )
            notice = (
                f"✅ Имя аккаунта изменено на "
                f"«{formatting.escape_html(account.tag)}»."
            )
        else:
            raise ValueError("Не удалось определить редактируемый аккаунт")
    except ValueError as error:
        bot.reply_to(message, f"Не удалось сохранить имя аккаунта: {error}")
        return
    logger.info(
        "Game account %s completed user_id=%s account_id=%s",
        action,
        user_id,
        account.account_id,
    )
    bot.delete_state(user_id)
    _open_destination(
        message,
        bot,
        destination if destination in DESTINATIONS else "accounts",
        notice,
    )


def select_account(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, _, _ = get_ids(callback_query)
    try:
        _, _, destination, encoded_account_id = callback_query.data.split("/")
        account_id = int(encoded_account_id)
        database = user_data.get_user_data_db()
        active = database.get_active_account(user_id)
        if active is not None and active.account_id == account_id:
            bot.answer_callback_query(callback_query.id, "Аккаунт уже выбран")
            return
        account = database.select_account(user_id, account_id)
    except (ValueError, TypeError) as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return
    notice = (
        "✅ Активный аккаунт: "
        f"<b>{formatting.escape_html(account.tag)}</b>."
    )
    _open_destination(
        callback_query,
        bot,
        destination,
        "" if destination == "accounts" else notice,
    )


def request_delete(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    accounts = user_data.get_user_data_db().get_accounts(user_id)
    candidates = [account for account in accounts if not account.is_active]
    if not candidates:
        accounts_menu(callback_query, bot)
        return
    keyboard = InlineKeyboardMarkup(row_width=1)
    for account in candidates:
        keyboard.add(
            Button(
                account.tag,
                f"accounts/delete/confirm/{account.account_id}",
            ).inline()
        )
    keyboard.add(Button("Отмена", "accounts").inline())
    bot.edit_message_text(
        "<b>Удаление аккаунта</b>\n\n"
        "Выберите неактивный аккаунт, который нужно удалить.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def confirm_delete(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    try:
        account_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
        account = next(
            account
            for account in user_data.get_user_data_db().get_accounts(user_id)
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
            "Да, удалить вместе с данными",
            f"accounts/delete/{account.account_id}",
        ).inline()
    )
    keyboard.add(Button("Отмена", "accounts/delete").inline())
    bot.edit_message_text(
        f"Удалить аккаунт <b>{formatting.escape_html(account.tag)}</b>?\n\n"
        "Все сохранённые для него ресурсы и настройки будут удалены безвозвратно.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def delete_account(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, _, _ = get_ids(callback_query)
    try:
        account_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
        user_data.get_user_data_db().delete_account(user_id, account_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return
    accounts_menu(callback_query, bot, "✅ Игровой аккаунт и его данные удалены.")


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        accounts_menu,
        func=empty_filter,
        button=r"accounts(?:/(resources|technologies|pets|war_calculator))?",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        request_add,
        func=empty_filter,
        button=(
            r"accounts/add"
            r"(?:/(accounts|resources|technologies|pets|war_calculator))?"
        ),
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        request_rename,
        func=empty_filter,
        button="accounts/rename",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        select_account,
        func=empty_filter,
        button=(
            r"accounts/select/"
            r"(accounts|resources|technologies|pets|war_calculator)/[0-9]+"
        ),
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        request_delete,
        func=empty_filter,
        button="accounts/delete",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        confirm_delete,
        func=empty_filter,
        button=r"accounts/delete/confirm/[0-9]+",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        delete_account,
        func=empty_filter,
        button=r"accounts/delete/[0-9]+",
        is_private=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        save_nickname,
        content_types=["text"],
        chat_types=["private"],
        state=GameAccountStates.nickname,
        pass_bot=True,
    )
