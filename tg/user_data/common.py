from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    THOUSAND_INPUT_FIELDS,
    TRACKED_FIELDS,
    ResourceField,
    UserData,
)
import tg.user_data as user_data
from tg.clans import get_user_clans
from tg.utils import Button, format_points, get_ids, get_username


@dataclass(frozen=True)
class ActiveUserResult:
    user: Optional[UserData]
    is_new_user: bool
    group_tag_found: bool | None
    clan_selection_required: bool = False


@dataclass(frozen=True)
class MenuContent:
    text: str
    keyboard: InlineKeyboardMarkup


FIELD_BUTTON_TITLES = {
    "mount_keys": "🔑 Ключи",
    "skills": "🎟 Билеты",
    "shells": "🥚 Скорлупа",
    "hammers": "🔨 Молотки",
    "pets": "🐾 Питомцы",
    "unmerged_mounts": "🐎 Маунты",
    "forge_level": "🔥 Кузница",
    "skill_summon_cost": "🎟 Призыв навыков",
    "extra_egg_chance": "🥚 Шанс яйца",
    "mount_summon_cost": "🐎 Призыв маунта",
    "extra_mount_chance": "✨ Доп. маунт",
}


def ensure_active_user(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> ActiveUserResult:
    user_id = get_ids(message)[0]
    username = get_username(message)
    database = user_data.get_user_data_db()
    account = database.get_active_account(user_id)
    if account is not None:
        database.update_username(user_id, username)
        user = database.get_user(user_id)
        if user is None:
            raise RuntimeError("Active game account has no user data")
        return ActiveUserResult(
            user,
            is_new_user=False,
            group_tag_found=None,
        )

    database.update_username(user_id, username)
    groups = get_user_clans(
        bot, user_id, user_data.get_access_group_db().get_groups()
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    for group in groups:
        keyboard.add(
            Button(
                f"🏰 {group.title}", f"accounts/create/{group.group_id}"
            ).inline()
        )
    text = (
        "<b>Выберите клан игрового аккаунта</b>\n\n"
        "Аккаунт будет учитываться только в данных выбранного клана."
        if groups
        else "Не удалось найти зарегистрированный клан, в котором вы состоите."
    )
    chat_id, message_id = get_ids(message)[1:]
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
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
    value_lines = []
    for field in fields:
        value = user.get_value(field.name)
        if field in RESOURCE_FIELDS and Decimal(value) >= Decimal("1000"):
            value = format_points(Decimal(value))
        line = f"{field.title}: <b>{value}</b>"
        if field in TRACKED_FIELDS:
            updated_on = user.get_updated_on(field.name)
            updated_label = (
                updated_on.strftime("%d.%m.%Y") if updated_on else "никогда"
            )
            line += f" <i>(обновлено: {updated_label})</i>"
        value_lines.append(line)
    values = "\n".join(value_lines)
    text = (
        f"<b>{title}</b>\n"
        f"Игровой аккаунт: <b>{formatting.escape_html(user.tag.value)}</b>\n\n"
        f"{values}\n\nВыберите показатель для изменения."
    )
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.row(
        Button("🔄 Аккаунт", f"accounts/{section}").inline(),
        Button("📝 Заполнить всё", f"user_data/fill/{section}").inline(),
    )
    keyboard.add(
        *(
            Button(
                FIELD_BUTTON_TITLES.get(field.name, field.title),
                f"user_data/edit/{field.name}",
            ).inline()
            for field in fields
        )
    )
    keyboard.row(Button("⬅️ Назад в меню", "home").inline())

    return MenuContent(text, keyboard)


def deliver_menu(
    update: Union[Message, CallbackQuery],
    bot: TeleBot,
    content: MenuContent,
) -> None:
    if isinstance(update, CallbackQuery):
        callback_message = update.message
        bot.edit_message_text(
            content.text,
            callback_message.chat.id,
            callback_message.id,
            reply_markup=content.keyboard,
        )
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
