from typing import Sequence, Union

from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.user_data import (
    EDITABLE_FIELDS,
    RESOURCE_FIELDS,
    TECHNOLOGY_FIELDS,
    ResourceField,
    THOUSAND_INPUT_FIELDS,
    parse_editable_field_value,
)
from tg.utils import Button, empty_filter, get_ids, get_username


class EditUserDataStates(StatesGroup):
    value = State()
    fill_values = State()


SECTION_FIELDS = {
    "resources": RESOURCE_FIELDS,
    "technologies": TECHNOLOGY_FIELDS,
}


def _section_menu(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    title: str,
    section: str,
    fields: Sequence[ResourceField],
    notice: str = "",
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    username = get_username(message)
    logger.debug(
        "Opening user data section=%s for user_id=%s username=%s",
        section,
        user_id,
        username,
    )
    bot.delete_state(user_id)
    user = get_user_data_db().get_or_create(user_id, username)

    values = "\n".join(
        f"{field.title}: <b>{user.get_value(field.name)}</b>" for field in fields
    )
    text = f"<b>{title}</b>\n\n{values}\n\nВыберите показатель для изменения."
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            f"Заполнить все: {title.lower()}",
            f"user_data/fill/{section}",
        ).inline()
    )
    for field in fields:
        keyboard.add(
            Button(field.title, f"user_data/edit/{field.name}").inline()
        )
    keyboard.add(Button("Назад в меню", "home").inline())

    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def _value_input_hint(field: ResourceField) -> str:
    if field.name in THOUSAND_INPUT_FIELDS:
        return "Введите число в тысячах с одним знаком после запятой, например: 1.5."
    return "Допустимо целое неотрицательное число."


def resources_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    _section_menu(message, bot, "Ресурсы", "resources", RESOURCE_FIELDS, notice)


def technologies_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    _section_menu(
        message, bot, "Технологии", "technologies", TECHNOLOGY_FIELDS, notice
    )


def request_value(callback_query: CallbackQuery, bot: TeleBot) -> None:
    field_name = callback_query.data.rsplit("/", maxsplit=1)[-1]
    field = EDITABLE_FIELDS.get(field_name)
    if field is None:
        logger.warning(
            "Unknown user data field requested by user_id=%s username=%s field=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            field_name,
        )
        bot.answer_callback_query(callback_query.id, "Показатель не найден")
        return

    section = "resources" if field in RESOURCE_FIELDS else "technologies"
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
        f"{_value_input_hint(field)}",
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
        f"{_value_input_hint(field)}"
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

    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "User data section fill started user_id=%s username=%s section=%s",
        user_id,
        get_username(callback_query),
        section,
    )
    bot.set_state(user_id, EditUserDataStates.fill_values)
    bot.add_data(user_id, fill_section=section, fill_index=0, fill_values={})

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Отмена", section).inline())
    bot.edit_message_text(
        _fill_prompt(
            "ресурсы" if section == "resources" else "технологии",
            fields,
            0,
        ),
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def save_value(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    username = get_username(message)
    with bot.retrieve_data(user_id) as data:
        field_name = data.get("field_name")
        section = data.get("section")

    field = EDITABLE_FIELDS.get(field_name)
    if field is None or section not in {"resources", "technologies"}:
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
    except ValueError:
        logger.info(
            "Invalid user data input user_id=%s username=%s field=%s",
            user_id,
            username,
            field_name,
        )
        bot.reply_to(message, _value_input_hint(field))
        return

    try:
        get_user_data_db().set_value(
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
        resources_menu(message, bot, notice)
    else:
        technologies_menu(message, bot, notice)


def save_all_values(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    username = get_username(message)
    with bot.retrieve_data(user_id) as data:
        section = data.get("fill_section")
        index = data.get("fill_index")
        values = data.get("fill_values")
    fields = SECTION_FIELDS.get(section) if isinstance(section, str) else None

    if (
        not isinstance(section, str)
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
    except ValueError:
        logger.info(
            "Invalid section input user_id=%s username=%s section=%s field=%s",
            user_id,
            username,
            section,
            field.name,
        )
        bot.reply_to(message, _value_input_hint(field))
        return

    values[field.name] = value
    next_index = index + 1
    if next_index < len(fields):
        logger.debug(
            "User data section fill progress user_id=%s username=%s section=%s step=%d/%d",
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
        keyboard.add(Button("Отмена", section).inline())
        bot.send_message(
            chat_id,
            _fill_prompt(
                "ресурсы" if section == "resources" else "технологии",
                fields,
                next_index,
            ),
            reply_markup=keyboard,
        )
        return

    try:
        get_user_data_db().set_values(user_id, username, values)
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
    bot.send_message(
        chat_id,
        "✅ Все значения раздела сохранены.",
    )
    if section == "resources":
        resources_menu(message, bot)
    else:
        technologies_menu(message, bot)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering user data handlers")
    bot.register_callback_query_handler(
        resources_menu,
        func=empty_filter,
        button="resources",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        technologies_menu,
        func=empty_filter,
        button="technologies",
        is_private=True,
        pass_bot=True,
    )
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
