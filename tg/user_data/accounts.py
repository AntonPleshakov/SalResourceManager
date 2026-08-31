from typing import Union

from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.user_data.common import ensure_active_user
from tg.utils import Button, empty_filter, get_ids, get_username


class GameAccountStates(StatesGroup):
    nickname = State()


DESTINATIONS = {"resources", "technologies", "pets", "war_calculator"}


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
    if not accounts:
        active_user = ensure_active_user(message, bot)
        if active_user.user is None:
            return
        accounts = database.get_accounts(user_id)
    active = next((account for account in accounts if account.is_active), None)
    destination = _requested_destination(message)
    lines = ["<b>Игровые аккаунты</b>"]
    if accounts:
        active_tag = (
            formatting.escape_html(active.tag) if active is not None else "не выбран"
        )
        clan_title = formatting.escape_html(active.clan_title) if active else ""
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
        if account.is_active:
            continue
        keyboard.add(
            Button(
                f"🔄 {account.tag} · {account.clan_title}",
                f"accounts/select/{destination}/{account.account_id}",
            ).inline()
        )
    account_actions = [
        Button("➕ Добавить", f"accounts/add/{destination}").inline()
    ]
    if active is not None:
        account_actions.append(Button("✏️ Переименовать", "accounts/rename").inline())
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
    user_id, chat_id, _ = get_ids(message)
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
        request_add_nickname,
        func=empty_filter,
        button=(
            r"accounts/add/"
            r"(accounts|resources|technologies|pets|war_calculator)"
            r"/clan/-?[0-9]+"
        ),
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        create_initial_account,
        func=empty_filter,
        button=r"accounts/create/-?[0-9]+",
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
