from decimal import Decimal
from typing import Sequence, Union

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
from resources.user_data import (
    RESOURCE_FIELDS,
    THOUSAND_INPUT_FIELDS,
    TRACKED_FIELDS,
    ResourceField,
)
import tg.user_data as user_data
from tg.utils import Button, format_points, get_ids, get_username


def _get_group_tag(bot: TeleBot, user_id: int) -> str | None:
    try:
        group_id = user_data.get_access_group_db().get_group_id()
    except RuntimeError:
        return None
    if group_id is None:
        return None
    try:
        member = bot.get_chat_member(group_id, user_id)
        return (
            getattr(member, "custom_title", None)
            or getattr(member, "tag", None)
            or ""
        )
    except Exception as error:
        logger.warning(
            "Unable to get group tag for user_id=%s: %s",
            user_id,
            type(error).__name__,
        )
        return None


def section_menu(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    title: str,
    section: str,
    fields: Sequence[ResourceField],
    notice: str = "",
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    username = get_username(message)
    tag = user_data._get_group_tag(bot, user_id)
    logger.debug(
        "Opening user data section=%s for user_id=%s username=%s",
        section,
        user_id,
        username,
    )
    bot.delete_state(user_id)
    user = user_data.get_user_data_db().get_or_create(user_id, username, tag)

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
    text = f"<b>{title}</b>\n\n{values}\n\nВыберите показатель для изменения."
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("Заполнить все", f"user_data/fill/{section}").inline()
    )
    for field in fields:
        keyboard.add(Button(field.title, f"user_data/edit/{field.name}").inline())
    keyboard.add(Button("Назад в меню", "home").inline())

    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def value_input_hint(field: ResourceField) -> str:
    if field.name == "eggs_per_hatch_batch":
        return "Введите целое число от 2 до 4."
    if field.name in THOUSAND_INPUT_FIELDS:
        return "Введите число в тысячах с одним знаком после запятой, например: 1.5."
    return "Допустимо целое неотрицательное число."
