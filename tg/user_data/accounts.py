from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.user_data.account.handlers import register_handlers
from tg.user_data.account.deletion import (
    confirm_delete,
    delete_account,
    request_delete,
)
from tg.user_data.account.menu import accounts_menu
from tg.user_data.account.routing import (
    DESTINATIONS,
    open_destination as _open_destination,
    requested_destination as _requested_destination,
)
from tg.utils import Button, get_ids, get_username


class GameAccountStates(StatesGroup):
    nickname = State()


def _get_group_tag(bot: TeleBot, user_id: int, group_id: int) -> str | None:
    try:
        member = bot.get_chat_member(group_id, user_id)
        if member.status in {"creator", "administrator"}:
            return member.custom_title or ""
        if member.status in {"member", "restricted"}:
            return member.tag or ""
        return ""
    except Exception as error:
        logger.warning(
            "Unable to get group tag for user_id=%s: %s",
            user_id,
            type(error).__name__,
        )
        return None


def _request_nickname(
    callback_query: CallbackQuery,
    bot: TeleBot,
    action: str,
    clan_id: int | None = None,
    destination: str | None = None,
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    account = user_data.get_user_data_db().get_active_account(user_id)
    if action == "rename" and account is None:
        accounts_menu(callback_query, bot)
        return
    bot.set_state(user_id, GameAccountStates.nickname)
    destination = destination or _requested_destination(callback_query)
    bot.add_data(
        user_id,
        account_action=action,
        account_id=None if account is None else account.account_id,
        account_destination=destination,
        account_clan_id=clan_id,
    )
    if action == "add":
        text = "Введите имя нового игрового аккаунта."
    else:
        text = (
            f"Введите новое имя для аккаунта "
            f"«{formatting.escape_html(account.tag)}»."
        )
    keyboard = InlineKeyboardMarkup(row_width=1)
    cancel_callback = (
        f"accounts/{destination}" if destination in DESTINATIONS else "accounts"
    )
    keyboard.add(Button("✖️ Отмена", cancel_callback).inline())
    bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)


def request_add(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    groups = get_user_clans(
        bot,
        user_id,
        user_data.get_access_group_db().get_groups(),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    destination = _requested_destination(callback_query)
    for group in groups:
        keyboard.add(
            Button(
                f"🏰 {group.title}",
                f"accounts/add/{destination}/clan/{group.group_id}",
            ).inline()
        )
    cancel_callback = (
        f"accounts/{destination}" if destination in DESTINATIONS else "accounts"
    )
    keyboard.add(Button("✖️ Отмена", cancel_callback).inline())
    text = (
        "<b>Новый игровой аккаунт</b>\n\nВыберите клан аккаунта."
        if groups
        else "Не удалось найти зарегистрированный клан, в котором вы состоите."
    )
    bot.edit_message_text(
        text,
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def request_add_nickname(callback_query: CallbackQuery, bot: TeleBot) -> None:
    try:
        destination = callback_query.data.split("/")[2]
        clan_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
    except ValueError:
        bot.answer_callback_query(
            callback_query.id, "Клан не найден", show_alert=True
        )
        return
    groups = get_user_clans(
        bot,
        callback_query.from_user.id,
        user_data.get_access_group_db().get_groups(),
    )
    if clan_id not in {group.group_id for group in groups}:
        bot.answer_callback_query(
            callback_query.id,
            "Вы не состоите в выбранном клане",
            show_alert=True,
        )
        return
    _request_nickname(
        callback_query, bot, "add", clan_id, destination=destination
    )


def request_rename(callback_query: CallbackQuery, bot: TeleBot) -> None:
    _request_nickname(callback_query, bot, "rename")


def create_initial_account(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = callback_query.from_user.id
    try:
        clan_id = int(callback_query.data.rsplit("/", maxsplit=1)[-1])
    except ValueError:
        bot.answer_callback_query(
            callback_query.id, "Клан не найден", show_alert=True
        )
        return
    groups = get_user_clans(
        bot, user_id, user_data.get_access_group_db().get_groups()
    )
    if clan_id not in {group.group_id for group in groups}:
        bot.answer_callback_query(
            callback_query.id,
            "Вы не состоите в выбранном клане",
            show_alert=True,
        )
        return
    database = user_data.get_user_data_db()
    existing = database.get_active_account(user_id)
    if existing is not None:
        accounts_menu(callback_query, bot)
        return
    group_tag = _get_group_tag(bot, user_id, clan_id) or ""
    username = get_username(callback_query)
    account = database.add_account(
        user_id,
        username,
        group_tag or username,
        clan_id=clan_id,
    )
    created_user = database.get_user(user_id, account.account_id)
    if created_user is None:
        raise RuntimeError("Created game account has no user data")
    from tg.onboarding import show_created_account_welcome

    show_created_account_welcome(
        callback_query, bot, created_user, bool(group_tag)
    )


def save_nickname(message: Message, bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    with bot.retrieve_data(user_id) as data:
        action = data.get("account_action")
        account_id = data.get("account_id")
        destination = data.get("account_destination")
        clan_id = data.get("account_clan_id")
    try:
        if action == "add":
            if not isinstance(clan_id, int):
                raise ValueError("Не выбран клан игрового аккаунта")
            available_clan_ids = {
                group.group_id
                for group in get_user_clans(
                    bot,
                    user_id,
                    user_data.get_access_group_db().get_groups(),
                )
            }
            if clan_id not in available_clan_ids:
                raise ValueError("Вы не состоите в выбранном клане")
            account = user_data.get_user_data_db().add_account(
                user_id,
                get_username(message),
                message.text,
                clan_id=clan_id,
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
    user_id = get_ids(callback_query)[0]
    try:
        destination, encoded_account_id = callback_query.data.split("/")[2:]
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
