from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.rich import (
    confirmation_buttons,
    edit_rich_message,
    heading,
    input_rich_message,
    notice as rich_notice,
)
from tg.user_data.common import (
    build_clan_selection_message,
    get_current_accounts,
    prompt_for_account_clan,
)
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
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(callback_query, bot, database)
    if accounts is None:
        return
    account = next((account for account in accounts if account.is_active), None)
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
    destination = _requested_destination(callback_query)
    cancel_callback = (
        f"accounts/{destination}" if destination in DESTINATIONS else "accounts"
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        build_clan_selection_message(
            groups,
            f"accounts/add/{destination}/clan",
            title="Новый игровой аккаунт",
            cancel_callback=cancel_callback,
        ),
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


def request_move(callback_query: CallbackQuery, bot: TeleBot) -> None:
    accounts = get_current_accounts(callback_query, bot)
    if accounts is None:
        return
    account = next((account for account in accounts if account.is_active), None)
    if account is None:
        accounts_menu(callback_query, bot)
        return
    destination = callback_query.data.rsplit("/", maxsplit=1)[-1]
    if destination not in DESTINATIONS | {"accounts"}:
        destination = "accounts"
    prompt_for_account_clan(
        callback_query,
        bot,
        account.account_id,
        destination,
    )


def move_account(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = callback_query.from_user.id
    try:
        parts = callback_query.data.split("/")
        account_id = int(parts[2])
        clan_id = int(parts[4])
        destination = parts[5] if len(parts) > 5 else "accounts"
    except (IndexError, ValueError):
        bot.answer_callback_query(
            callback_query.id, "Не удалось выбрать клан", show_alert=True
        )
        return
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(callback_query, bot, database)
    if accounts is None:
        return
    if account_id not in {account.account_id for account in accounts}:
        bot.answer_callback_query(
            callback_query.id, "Игровой аккаунт не найден", show_alert=True
        )
        return
    available_clan_ids = {
        group.group_id
        for group in get_user_clans(
            bot, user_id, user_data.get_access_group_db().get_groups()
        )
    }
    if clan_id not in available_clan_ids:
        bot.answer_callback_query(
            callback_query.id,
            "Вы не состоите в выбранном клане",
            show_alert=True,
        )
        return
    try:
        account = database.move_account(user_id, account_id, clan_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return
    notice = (
        "✅ Клан аккаунта "
        f"«{formatting.escape_html(account.tag)}» изменён."
    )
    _open_destination(
        callback_query,
        bot,
        destination if destination in DESTINATIONS else "accounts",
        notice,
    )


def leave_clan(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id = callback_query.from_user.id
    try:
        parts = callback_query.data.split("/")
        account_id = int(parts[2])
        destination = parts[-1]
        if destination not in DESTINATIONS | {"accounts"}:
            destination = "accounts"
    except (IndexError, ValueError) as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(callback_query, bot, database)
    if accounts is None:
        return
    current = next(
        (account for account in accounts if account.account_id == account_id),
        None,
    )
    if current is None or current.clan_id is None:
        bot.answer_callback_query(
            callback_query.id,
            "Клан игрового аккаунта уже не выбран",
            show_alert=True,
        )
        return
    is_confirmed = len(parts) >= 6 and parts[-2] == "confirm"
    if not is_confirmed:
        edit_rich_message(
            bot,
            callback_query.message.chat.id,
            callback_query.message.id,
            input_rich_message(
                (
                    heading(f"Отвязать аккаунт «{current.tag}» от клана?"),
                    rich_notice(
                        "Ресурсы и настройки сохранятся, но аккаунт перестанет "
                        "участвовать в отчётах и расчётах клана."
                    ),
                    confirmation_buttons(
                        "🔗 Отвязать от клана",
                        f"accounts/move/{account_id}/leave/confirm/"
                        f"{destination}",
                        "✖️ Отмена",
                        (
                            f"accounts/{destination}"
                            if destination != "accounts"
                            else "accounts"
                        ),
                        destructive=True,
                    ),
                )
            ),
        )
        return
    try:
        account = database.detach_account_from_clan(user_id, account_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return
    _open_destination(
        callback_query,
        bot,
        destination,
        "✅ Аккаунт "
        f"«{formatting.escape_html(account.tag)}» больше не привязан к клану. "
        "Данные аккаунта сохранены.",
    )


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
    accounts = get_current_accounts(callback_query, bot, database)
    if accounts is None:
        return
    existing = next((account for account in accounts if account.is_active), None)
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
    created_user = database.get_assigned_user(user_id, account.account_id)
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
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(message, bot, database)
    if accounts is None:
        return
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
            account = database.add_account(
                user_id,
                get_username(message),
                message.text,
                clan_id=clan_id,
            )
            notice = (
                f"✅ Аккаунт «{formatting.escape_html(account.tag)}» добавлен и выбран."
            )
        elif action == "rename" and isinstance(account_id, int):
            if account_id not in {account.account_id for account in accounts}:
                raise ValueError("Игровой аккаунт не найден")
            account = database.rename_account(user_id, account_id, message.text)
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
        accounts = get_current_accounts(callback_query, bot, database)
        if accounts is None:
            return
        selected = next(
            (account for account in accounts if account.account_id == account_id),
            None,
        )
        if selected is None:
            raise ValueError("Игровой аккаунт не найден")
        if destination in DESTINATIONS and selected.clan_id is None:
            prompt_for_account_clan(
                callback_query,
                bot,
                account_id,
                destination,
            )
            return
        active = next((account for account in accounts if account.is_active), None)
        if active is not None and active.account_id == account_id:
            if destination in DESTINATIONS:
                _open_destination(callback_query, bot, destination)
            else:
                bot.answer_callback_query(
                    callback_query.id, "Аккаунт уже выбран"
                )
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
