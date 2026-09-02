from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import List, Optional, Sequence, Union

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
)

from common.datetime_utils import format_last_update
from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    THOUSAND_INPUT_FIELDS,
    TRACKED_FIELDS,
    GameAccount,
    ResourceField,
    UserData,
)
import tg.user_data as user_data
from tg.clans import (
    ClanMembershipCheckError,
    get_user_clans,
    refresh_user_accounts,
)
from tg.rich import button_row, callback_button, input_rich_message
from tg.utils import Button, format_points, get_ids, get_username


@dataclass(frozen=True)
class ActiveUserResult:
    user: Optional[UserData]
    is_new_user: bool
    group_tag_found: bool | None
    clan_selection_required: bool = False


@dataclass(frozen=True)
class MenuContent:
    text: str | None = None
    keyboard: InlineKeyboardMarkup | None = None
    rich_message: InputRichMessage | None = None


def _deliver_account_clan_prompt(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    chat_id, message_id = get_ids(message)[1:]
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def get_current_accounts(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    database=None,
) -> Optional[List[GameAccount]]:
    """Return accounts only after their current clan access was verified."""
    user_id = get_ids(message)[0]
    database = database or user_data.get_user_data_db()
    try:
        refresh_user_accounts(bot, user_id, database)
    except ClanMembershipCheckError:
        _deliver_account_clan_prompt(
            message,
            bot,
            "Не удалось проверить участие в клане. Попробуйте ещё раз позже.",
            InlineKeyboardMarkup(),
        )
        return None
    return database.get_accounts(user_id)


def prompt_for_account_clan(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    account_id: int | None,
) -> None:
    user_id = get_ids(message)[0]
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(message, bot, database)
    if accounts is None:
        return
    account = next(
        (
            account
            for account in accounts
            if account.account_id == account_id
        ),
        None,
    )
    current_clan_id = None if account is None else account.clan_id
    groups = get_user_clans(
        bot, user_id, user_data.get_access_group_db().get_groups()
    )
    target_groups = [
        group for group in groups if group.group_id != current_clan_id
    ]
    keyboard = InlineKeyboardMarkup(row_width=1)
    callback_prefix = (
        "accounts/create"
        if account_id is None
        else f"accounts/move/{account_id}/clan"
    )
    for group in target_groups:
        keyboard.add(
            Button(
                f"🏰 {group.title}", f"{callback_prefix}/{group.group_id}"
            ).inline()
        )
    if account_id is not None:
        keyboard.add(Button("⬅️ Назад к аккаунтам", "accounts").inline())
    text = (
        "<b>Выберите клан игрового аккаунта</b>\n\n"
        "Аккаунт будет учитываться только в данных выбранного клана."
        if target_groups
        else (
            "Нет других доступных кланов для этого аккаунта."
            if current_clan_id is not None
            else "Не удалось найти зарегистрированный клан, в котором вы состоите."
        )
    )
    _deliver_account_clan_prompt(message, bot, text, keyboard)


def ensure_active_user(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> ActiveUserResult:
    user_id = get_ids(message)[0]
    username = get_username(message)
    database = user_data.get_user_data_db()
    accounts = get_current_accounts(message, bot, database)
    if accounts is None:
        return ActiveUserResult(
            None,
            is_new_user=False,
            group_tag_found=None,
        )
    account = next((account for account in accounts if account.is_active), None)
    if account is not None and account.clan_id is not None:
        database.update_username(user_id, username)
        user = database.get_assigned_user(user_id)
        if user is None:
            raise RuntimeError("Active game account has no user data")
        return ActiveUserResult(
            user,
            is_new_user=False,
            group_tag_found=None,
        )

    database.update_username(user_id, username)
    prompt_for_account_clan(
        message,
        bot,
        None if account is None else account.account_id,
    )
    return ActiveUserResult(
        None,
        is_new_user=False,
        group_tag_found=None,
        clan_selection_required=True,
    )


def get_active_user_or_prompt(
    message: Union[Message, CallbackQuery], bot: TeleBot
):
    return ensure_active_user(message, bot).user


def build_section_menu(
    user: UserData,
    title: str,
    section: str,
    fields: Sequence[ResourceField],
    notice: str = "",
) -> MenuContent:
    parts = []
    if notice:
        parts.append(f"<blockquote>{notice}</blockquote>")
    parts.extend(
        (
            f"<h2>{escape(title)}</h2>",
            "<p>Игровой аккаунт: "
            f"<b>{escape(str(user.tag.value))}</b></p>",
        )
    )
    for field in fields:
        value = user.get_value(field.name)
        if field in RESOURCE_FIELDS and Decimal(value) >= Decimal("1000"):
            value = format_points(Decimal(value))
        details = ""
        if field in TRACKED_FIELDS:
            updated_on = user.get_updated_on(field.name)
            updated_label = format_last_update(updated_on)
            details = f"<br><i>Обновлено: {escape(updated_label)}</i>"
        parts.append(
            "<p>"
            f"{escape(field.title)}: <b>{escape(str(value))}</b>"
            f"{details}<br>"
            f"{callback_button('✏️ Изменить', f'user_data/edit/{field.name}')}"
            "</p>"
        )
    parts.append(
        button_row(
            (
                callback_button("🔄 Аккаунт", f"accounts/{section}"),
                callback_button(
                    "📝 Заполнить всё",
                    f"user_data/fill/{section}",
                    style="primary",
                ),
            )
        )
    )
    parts.append(
        button_row(
            (callback_button("⬅️ Назад в меню", "home"),),
            align="left",
        )
    )
    return MenuContent(rich_message=input_rich_message(parts))


def edit_menu_message(
    bot: TeleBot,
    chat_id: int,
    message_id: int,
    content: MenuContent,
) -> None:
    if content.rich_message is not None:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            rich_message=content.rich_message,
        )
        return

    bot.edit_message_text(
        content.text,
        chat_id,
        message_id,
        reply_markup=content.keyboard,
    )


def deliver_menu(
    update: Union[Message, CallbackQuery],
    bot: TeleBot,
    content: MenuContent,
) -> None:
    if isinstance(update, CallbackQuery):
        callback_message = update.message
        edit_menu_message(
            bot,
            callback_message.chat.id,
            callback_message.id,
            content,
        )
        return

    if content.rich_message is not None:
        bot.send_rich_message(update.chat.id, content.rich_message)
        return

    bot.send_message(
        update.chat.id,
        content.text,
        reply_markup=content.keyboard,
    )


def show_section_menu(
    update: Union[Message, CallbackQuery],
    bot: TeleBot,
    title: str,
    section: str,
    fields: Sequence[ResourceField],
    notice: str = "",
) -> None:
    user_id = get_ids(update)[0]
    username = get_username(update)
    logger.debug(
        "Opening user data section=%s for user_id=%s username=%s",
        section,
        user_id,
        username,
    )
    bot.delete_state(user_id)
    user = get_active_user_or_prompt(update, bot)
    if user is None:
        return

    content = build_section_menu(user, title, section, fields, notice)
    deliver_menu(update, bot, content)


def value_input_hint(field: ResourceField) -> str:
    if field.name == "eggs_per_hatch_batch":
        return "Введите целое число от 2 до 4."
    if field.name == "forge_level":
        return "Введите целое число от 1 до 35."
    if field.name in {"skill_summon_cost", "mount_summon_cost"}:
        return "Введите целое число от 0 до 25 (%)."
    if field.name == "extra_mount_chance":
        return "Введите целое число от 0 до 50 (%)."
    if field.name in THOUSAND_INPUT_FIELDS:
        return "Введите число в тысячах: 0.12 или 0,12 = 120."
    return "Введите целое неотрицательное число."
