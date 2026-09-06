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

from common.datetime_utils import format_last_update, now, week_started_on
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
from tg.rich import (
    account_context,
    back_button,
    button_row,
    callback_button,
    deliver_rich_message,
    details,
    edit_rich_message,
    heading,
    highlight_metric,
    input_rich_message,
    notice as rich_notice,
)
from tg.utils import format_points, get_ids, get_username


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


def build_clan_selection_message(
    groups,
    callback_prefix: str,
    *,
    title: str,
    callback_suffix: str = "",
    cancel_callback: str | None = None,
    empty_message: str = (
        "Не найден зарегистрированный клан, в котором вы состоите."
    ),
) -> InputRichMessage:
    parts = [heading(title)]
    if groups:
        parts.append(
            "<p>Аккаунт будет учитываться только в данных выбранного "
            "клана.</p>"
        )
        for group in groups:
            parts.append(
                button_row(
                    (
                        callback_button(
                            f"🏰 {group.title}",
                            f"{callback_prefix}/{group.group_id}"
                            f"{callback_suffix}",
                        ),
                    )
                )
            )
    else:
        parts.append(f"<p>{escape(empty_message)}</p>")
    if cancel_callback:
        parts.append(back_button("✖️ Отмена", cancel_callback))
    return input_rich_message(parts)


def prompt_for_account_clan(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    account_id: int | None,
    destination: str = "accounts",
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
    callback_prefix = (
        "accounts/create"
        if account_id is None
        else f"accounts/move/{account_id}/clan"
    )
    title = (
        "Выберите другой клан"
        if current_clan_id is not None
        else "Выберите клан аккаунта"
    )
    rich_message = build_clan_selection_message(
        target_groups,
        callback_prefix,
        title=title,
        callback_suffix=(
            f"/{destination}"
            if account_id is not None and destination != "accounts"
            else ""
        ),
        cancel_callback=(
            f"accounts/{destination}"
            if account_id is not None and destination != "accounts"
            else "accounts" if account_id is not None else None
        ),
        empty_message=(
            "Нет других доступных кланов для этого аккаунта."
            if current_clan_id is not None
            else "Не найден зарегистрированный клан, в котором вы состоите."
        ),
    )
    deliver_rich_message(message, bot, rich_message)


def _requested_data_destination(
    message: Union[Message, CallbackQuery],
) -> str:
    if not isinstance(message, CallbackQuery):
        return "accounts"
    data = message.data
    candidate = data.split("/")[-1]
    if candidate in {"resources", "technologies", "pets", "war_calculator"}:
        return candidate
    if data.startswith("user_data/edit/"):
        field_name = candidate
        if field_name == "eggs_per_hatch_batch":
            return "pets"
        if field_name in {field.name for field in RESOURCE_FIELDS}:
            return "resources"
        return "technologies"
    if data.startswith("user_data/fill/technologies"):
        return "technologies"
    if data.startswith("user_data/fill/"):
        return "resources"
    if data.startswith("pets"):
        return "pets"
    if data.startswith("war_calculator"):
        return "war_calculator"
    return "accounts"


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
        _requested_data_destination(message),
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


def _field_update_details(user: UserData, field: ResourceField) -> str:
    updated_on = user.get_updated_on(field.name)
    if updated_on is None:
        return "<br><b>⚠️ Не обновлялось</b>"
    updated_label = escape(format_last_update(updated_on))
    if updated_on < week_started_on(now()):
        return f"<br><b>⚠️ Обновлено: {updated_label}</b>"
    return f"<br><i>Обновлено: {updated_label}</i>"


def _section_freshness(user: UserData, fields: Sequence[ResourceField]) -> str:
    tracked_fields = tuple(field for field in fields if field in TRACKED_FIELDS)
    if not tracked_fields:
        return ""
    cutoff = week_started_on(now())
    current = user.fields_updated_count_since(tracked_fields, cutoff)
    return highlight_metric(
        "Актуально с понедельника",
        f"{current} из {len(tracked_fields)}",
    )


def build_section_menu(
    user: UserData,
    title: str,
    section: str,
    fields: Sequence[ResourceField],
    notice: str = "",
) -> MenuContent:
    parts = []
    if notice:
        parts.append(rich_notice(notice))
    parts.extend(
        (
            heading(title),
            account_context(str(user.tag.value)),
            _section_freshness(user, fields),
        )
    )
    for field in fields:
        value = user.get_value(field.name)
        if field in RESOURCE_FIELDS and Decimal(value) >= Decimal("1000"):
            value = format_points(Decimal(value))
        field_details = ""
        if field in TRACKED_FIELDS:
            field_details = _field_update_details(user, field)
        parts.append(
            "<p>"
            f"{escape(field.title)}: <b>{escape(str(value))}</b>"
            f"{field_details}<br>"
            f"{callback_button('✏️ Изменить', f'user_data/edit/{field.name}')}"
            "</p>"
        )
    parts.append(
        button_row(
            (
                callback_button(
                    "🔄 Сменить аккаунт", f"accounts/{section}"
                ),
                callback_button(
                    "📝 Заполнить всё",
                    f"user_data/fill/{section}",
                    style="primary",
                ),
            )
        )
    )
    if section == "resources":
        parts.append(
            details(
                "Как определяется актуальность",
                "<p>Счётчик показывает, сколько ресурсов обновлено с "
                "03:00 понедельника. Для общего расчёта аккаунт включается, "
                "если за это время обновлён хотя бы один ресурс.</p>",
            )
        )
    elif section == "technologies":
        parts.append(
            details(
                "Когда обновлять технологии",
                "<p>Технологии не определяют свежесть ресурсов. Обновляйте "
                "их после изменения уровней или бонусов.</p>",
            )
        )
    parts.append(back_button("⬅️ Главное меню", "home"))
    return MenuContent(rich_message=input_rich_message(parts))


def edit_menu_message(
    bot: TeleBot,
    chat_id: int,
    message_id: int,
    content: MenuContent,
) -> None:
    if content.rich_message is not None:
        edit_rich_message(bot, chat_id, message_id, content.rich_message)
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
        deliver_rich_message(update, bot, content.rich_message)
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
        return (
            "Введите точное количество, например 120. Тысячи можно "
            "записать как 1.5, 1,5 или 1.5к = 1 500."
        )
    return "Введите целое неотрицательное число."
