from typing import Sequence

from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
from resources.user_data import (
    EDITABLE_FIELDS,
    RESOURCE_FIELDS,
    TRACKED_FIELDS,
    TECHNOLOGY_FIELDS,
    ResourceField,
    parse_editable_field_value,
)
import tg.user_data as user_data
from tg.user_data.common import value_input_hint
from tg.utils import Button, empty_filter, get_ids, get_username


class EditUserDataStates(StatesGroup):
    value = State()
    fill_values = State()


SECTION_FIELDS = {
    "resources": RESOURCE_FIELDS,
    "technologies": TECHNOLOGY_FIELDS,
}
SECTION_TITLES = {
    "resources": "ресурсы",
    "technologies": "технологии",
    "pets": "питомцы",
    "reminder": "данные из напоминания",
}


def request_value(callback_query: CallbackQuery, bot: TeleBot) -> None:
    field_name = callback_query.data.rsplit("/", maxsplit=1)[-1]
    field = EDITABLE_FIELDS.get(field_name)
    if field is None or (
        field not in TRACKED_FIELDS and field_name != "eggs_per_hatch_batch"
    ):
        logger.warning(
            "Unknown user data field requested by user_id=%s username=%s field=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            field_name,
        )
        bot.answer_callback_query(callback_query.id, "Показатель не найден")
        return

    if field in RESOURCE_FIELDS:
        section = "resources"
    elif field in TECHNOLOGY_FIELDS:
        section = "technologies"
    else:
        section = "pets"
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "User data edit started user_id=%s username=%s field=%s",
        user_id,
        get_username(callback_query),
        field_name,
    )
    bot.set_state(user_id, EditUserDataStates.value)
    bot.add_data(user_id, field_name=field_name, section=section)

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Отмена", section).inline())
    bot.edit_message_text(
        f"Введите новое значение для «{field.title}».\n"
        f"{value_input_hint(field)}",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def _fill_prompt(
    section: str, fields: Sequence[ResourceField], index: int
) -> str:
    field = fields[index]
    return (
        f"<b>Заполнение: {section} ({index + 1}/{len(fields)})</b>\n\n"
        f"Введите значение для «{field.title}».\n"
        f"{value_input_hint(field)}"
    )


def _start_fill(
    callback_query: CallbackQuery,
    bot: TeleBot,
    section: str,
    fields: Sequence[ResourceField],
    cancel_callback: str,
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "User data fill started user_id=%s username=%s section=%s fields=%s",
        user_id,
        get_username(callback_query),
        section,
        ",".join(field.name for field in fields),
    )
    bot.set_state(user_id, EditUserDataStates.fill_values)
    bot.add_data(
        user_id,
        fill_section=section,
        fill_field_names=[field.name for field in fields],
        fill_index=0,
        fill_values={},
    )

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Отмена", cancel_callback).inline())
    bot.edit_message_text(
        _fill_prompt(SECTION_TITLES[section], fields, 0),
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def fill_section(callback_query: CallbackQuery, bot: TeleBot) -> None:
    section = callback_query.data.rsplit("/", maxsplit=1)[-1]
    fields = SECTION_FIELDS.get(section)
    if fields is None:
        logger.warning(
            "Unknown user data section requested by user_id=%s username=%s section=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            section,
        )
        bot.answer_callback_query(callback_query.id, "Раздел не найден")
        return

    _start_fill(callback_query, bot, section, fields, section)


def fill_tracked_fields(callback_query: CallbackQuery, bot: TeleBot) -> None:
    encoded_indexes = callback_query.data.rsplit("/", maxsplit=1)[-1]
    try:
        indexes = {int(value) for value in encoded_indexes.split(",")}
    except ValueError:
        indexes = set()
    if not indexes or any(
        index < 0 or index >= len(TRACKED_FIELDS) for index in indexes
    ):
        logger.warning(
            "Invalid tracked fields requested by user_id=%s username=%s indexes=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            encoded_indexes,
        )
        bot.answer_callback_query(callback_query.id, "Показатели не найдены")
        return

    fields = tuple(
        field for index, field in enumerate(TRACKED_FIELDS) if index in indexes
    )
    _start_fill(callback_query, bot, "reminder", fields, "home")


def save_value(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    username = get_username(message)
    with bot.retrieve_data(user_id) as data:
        field_name = data.get("field_name")
        section = data.get("section")

    field = EDITABLE_FIELDS.get(field_name)
    if field is None or section not in {"resources", "technologies", "pets"}:
        logger.warning(
            "Invalid edit state for user_id=%s username=%s", user_id, username
        )
        bot.delete_state(user_id)
        bot.send_message(
            chat_id,
            "Не удалось определить редактируемый показатель. "
            "Откройте раздел заново.",
        )
        return

    try:
        value = parse_editable_field_value(field_name, message.text)
    except ValueError as error:
        logger.info(
            "Invalid user data input user_id=%s username=%s field=%s",
            user_id,
            username,
            field_name,
        )
        bot.reply_to(
            message,
            f"Значение для «{field.title}» не подходит: {error}\n"
            f"{value_input_hint(field)}",
        )
        return

    try:
        user_data.get_user_data_db().set_value(
            user_id, username, field_name, value
        )
    except ValueError as error:
        logger.warning(
            "Rejected user data value user_id=%s username=%s field=%s reason=%s",
            user_id,
            username,
            field_name,
            error,
        )
        bot.reply_to(message, f"Значение для «{field.title}» не подходит: {error}")
        return
    logger.info(
        "User data edit completed user_id=%s username=%s field=%s",
        user_id,
        username,
        field_name,
    )
    notice = f"✅ {field.title}: <b>{value}</b> — сохранено."
    if section == "resources":
        user_data.resources_menu(message, bot, notice)
    elif section == "technologies":
        user_data.technologies_menu(message, bot, notice)
    else:
        user_data.pets_menu(message, bot, notice)


def save_all_values(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    username = get_username(message)
    with bot.retrieve_data(user_id) as data:
        section = data.get("fill_section")
        field_names = data.get("fill_field_names")
        index = data.get("fill_index")
        values = data.get("fill_values")
    if field_names is None:
        fields = SECTION_FIELDS.get(section) if isinstance(section, str) else None
    elif (
        isinstance(field_names, list)
        and field_names
        and len(field_names) == len(set(field_names))
        and all(field_name in EDITABLE_FIELDS for field_name in field_names)
    ):
        fields = tuple(EDITABLE_FIELDS[field_name] for field_name in field_names)
    else:
        fields = None

    if (
        not isinstance(section, str)
        or section not in SECTION_TITLES
        or fields is None
        or not isinstance(index, int)
        or not 0 <= index < len(fields)
        or not isinstance(values, dict)
    ):
        logger.warning(
            "Invalid section fill state for user_id=%s username=%s",
            user_id,
            username,
        )
        bot.delete_state(user_id)
        bot.send_message(
            chat_id,
            "Не удалось продолжить заполнение. Откройте меню заново.",
        )
        return

    field = fields[index]
    try:
        value = parse_editable_field_value(field.name, message.text)
    except ValueError as error:
        logger.info(
            "Invalid section input user_id=%s username=%s section=%s field=%s",
            user_id,
            username,
            section,
            field.name,
        )
        bot.reply_to(
            message,
            f"Значение для «{field.title}» не подходит: {error}\n"
            f"{value_input_hint(field)}",
        )
        return

    values[field.name] = value
    next_index = index + 1
    if next_index < len(fields):
        logger.debug(
            "User data section fill progress user_id=%s username=%s "
            "section=%s step=%d/%d",
            user_id,
            username,
            section,
            next_index,
            len(fields),
        )
        bot.add_data(
            user_id,
            fill_section=section,
            fill_index=next_index,
            fill_values=values,
        )
        keyboard = InlineKeyboardMarkup(row_width=1)
        cancel_callback = section if section in SECTION_FIELDS else "home"
        keyboard.add(Button("Отмена", cancel_callback).inline())
        bot.send_message(
            chat_id,
            _fill_prompt(SECTION_TITLES[section], fields, next_index),
            reply_markup=keyboard,
        )
        return

    try:
        user_data.get_user_data_db().set_values(user_id, username, values)
    except ValueError as error:
        logger.warning(
            "Rejected user data section user_id=%s username=%s section=%s reason=%s",
            user_id,
            username,
            section,
            error,
        )
        bot.reply_to(message, f"Значение не подходит: {error}")
        return
    bot.delete_state(user_id)
    logger.info(
        "User data section fill completed user_id=%s username=%s section=%s fields=%d",
        user_id,
        username,
        section,
        len(values),
    )
    if section == "reminder":
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(Button("Назад в меню", "home").inline())
        bot.send_message(
            chat_id,
            "✅ Все данные из напоминания обновлены.",
            reply_markup=keyboard,
        )
    elif section == "resources":
        bot.send_message(chat_id, "✅ Все значения раздела сохранены.")
        user_data.resources_menu(message, bot)
    else:
        bot.send_message(chat_id, "✅ Все значения раздела сохранены.")
        user_data.technologies_menu(message, bot)


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        request_value,
        func=empty_filter,
        button=r"user_data/edit/[a-z_]+",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        fill_section,
        func=empty_filter,
        button=r"user_data/fill/(resources|technologies)",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        fill_tracked_fields,
        func=empty_filter,
        button=r"user_data/fill/tracked/[0-9,]+",
        is_private=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        save_value,
        content_types=["text"],
        chat_types=["private"],
        state=EditUserDataStates.value,
        pass_bot=True,
    )
    bot.register_message_handler(
        save_all_values,
        content_types=["text"],
        chat_types=["private"],
        state=EditUserDataStates.fill_values,
        pass_bot=True,
    )
