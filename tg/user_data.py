from decimal import Decimal
from typing import Sequence, Union

from telebot import TeleBot
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.user_data import get_user_data_db
from db.access_group import get_access_group_db
from logger.app_logger import logger
from resources.egg_levels import EGG_LEVELS, EggLevel
from resources.user_data import (
    EDITABLE_FIELDS,
    PET_SETTINGS_FIELDS,
    RESOURCE_FIELDS,
    TRACKED_FIELDS,
    TECHNOLOGY_FIELDS,
    ResourceField,
    THOUSAND_INPUT_FIELDS,
    parse_editable_field_value,
)
from tg.utils import (
    Button,
    empty_filter,
    format_points,
    get_ids,
    get_username,
)


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


def _get_group_tag(bot: TeleBot, user_id: int) -> str | None:
    try:
        group_id = get_access_group_db().get_group_id()
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
    tag = _get_group_tag(bot, user_id)
    logger.debug(
        "Opening user data section=%s for user_id=%s username=%s",
        section,
        user_id,
        username,
    )
    bot.delete_state(user_id)
    user = get_user_data_db().get_or_create(user_id, username, tag)

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
        Button(
            f"Заполнить все",
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
    if field.name == "eggs_per_hatch_batch":
        return "Введите целое число от 2 до 4."
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


def pets_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    username = get_username(message)
    tag = _get_group_tag(bot, user_id)
    bot.delete_state(user_id)
    user = get_user_data_db().get_or_create(user_id, username, tag)
    max_level = EggLevel(user.max_egg_level.value)
    batch_lines = []
    total_batches = 0
    for level in reversed(EGG_LEVELS):
        if level > max_level:
            continue
        count = getattr(user, level.batch_field_name).value
        total_batches += count
        if count:
            batch_lines.append(f"• {level.label}: <b>{count}</b>")
    batches = "\n".join(batch_lines) if batch_lines else "• не настроены"
    text = (
        "<b>Питомцы</b>\n\n"
        f"Яиц в одном пакете: <b>{user.eggs_per_hatch_batch.value}</b>\n"
        f"Максимальный уровень яйца: <b>{max_level.label}</b>\n"
        f"Пакетов в день: <b>{total_batches}</b>\n{batches}\n\n"
        "Выберите параметр для изменения."
    )
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            PET_SETTINGS_FIELDS[0].title,
            "user_data/edit/eggs_per_hatch_batch",
        ).inline()
    )
    keyboard.add(Button("Максимальный уровень яйца", "pets/max_level").inline())
    keyboard.add(Button("Пакеты для вылупления в день", "pets/batches").inline())
    keyboard.add(Button("Назад в меню", "home").inline())

    logger.debug(
        "Opening pet settings for user_id=%s username=%s",
        user_id,
        username,
    )
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def max_egg_level_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = get_user_data_db().get_or_create(
        user_id,
        get_username(callback_query),
        _get_group_tag(bot, user_id),
    )
    current_level = EggLevel(user.max_egg_level.value)
    keyboard = InlineKeyboardMarkup(row_width=1)
    for level in reversed(EGG_LEVELS):
        marker = " ✓" if level == current_level else ""
        keyboard.add(
            Button(
                f"{level.label}{marker}",
                f"pets/max_level/{level.value}",
            ).inline()
        )
    keyboard.add(Button("Назад к питомцам", "pets").inline())
    bot.edit_message_text(
        "<b>Максимальный уровень яйца</b>\n\n"
        "Выберите самый высокий доступный уровень.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def save_max_egg_level(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, _, _ = get_ids(callback_query)
    try:
        level = EggLevel(int(callback_query.data.rsplit("/", maxsplit=1)[-1]))
    except ValueError:
        bot.answer_callback_query(
            callback_query.id, "Уровень яйца не найден", show_alert=True
        )
        return

    values = {"max_egg_level": level.value}
    values.update(
        {
            candidate.batch_field_name: 0
            for candidate in EGG_LEVELS
            if candidate > level
        }
    )
    get_user_data_db().set_values(
        user_id,
        get_username(callback_query),
        values,
        tag=_get_group_tag(bot, user_id),
    )
    pets_menu(
        callback_query,
        bot,
        f"✅ Максимальный уровень: <b>{level.label}</b> — сохранён.",
    )


def hatch_batches_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = get_user_data_db().get_or_create(
        user_id,
        get_username(callback_query),
        _get_group_tag(bot, user_id),
    )
    max_level = EggLevel(user.max_egg_level.value)
    total_batches = sum(
        getattr(user, level.batch_field_name).value
        for level in EGG_LEVELS
        if level <= max_level
    )
    keyboard = InlineKeyboardMarkup(row_width=3)
    for level in reversed(EGG_LEVELS):
        if level > max_level:
            continue
        count = getattr(user, level.batch_field_name).value
        keyboard.row(
            Button("−", f"pets/batches/{level.value}/minus").inline(),
            Button(
                f"{level.label}: {count}",
                "pets/batches",
            ).inline(),
            Button("+", f"pets/batches/{level.value}/plus").inline(),
        )
    keyboard.add(Button("Готово", "pets").inline())
    bot.edit_message_text(
        "<b>Пакеты для вылупления в день</b>\n\n"
        "Укажите максимальное количество пакетов каждого уровня. "
        "Изменения сохраняются сразу.\n\n"
        f"Всего в день: <b>{total_batches}</b>",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def change_hatch_batch_count(callback_query: CallbackQuery, bot: TeleBot) -> None:
    parts = callback_query.data.split("/")
    try:
        level = EggLevel(int(parts[-2]))
        delta = {"minus": -1, "plus": 1}[parts[-1]]
    except (KeyError, ValueError):
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось изменить количество пакетов",
            show_alert=True,
        )
        return

    user_id, _, _ = get_ids(callback_query)
    username = get_username(callback_query)
    tag = _get_group_tag(bot, user_id)
    user = get_user_data_db().get_or_create(user_id, username, tag)
    if level > EggLevel(user.max_egg_level.value):
        bot.answer_callback_query(
            callback_query.id,
            "Сначала повысьте максимальный уровень яйца",
            show_alert=True,
        )
        return
    current = getattr(user, level.batch_field_name).value
    get_user_data_db().set_value(
        user_id,
        username,
        level.batch_field_name,
        max(0, current + delta),
        tag=tag,
    )
    hatch_batches_menu(callback_query, bot)


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
            f"{_value_input_hint(field)}",
        )
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
    elif section == "technologies":
        technologies_menu(message, bot, notice)
    else:
        pets_menu(message, bot, notice)


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
            f"{_value_input_hint(field)}",
        )
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
        cancel_callback = section if section in SECTION_FIELDS else "home"
        keyboard.add(Button("Отмена", cancel_callback).inline())
        bot.send_message(
            chat_id,
            _fill_prompt(SECTION_TITLES[section], fields, next_index),
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
        resources_menu(message, bot)
    else:
        bot.send_message(chat_id, "✅ Все значения раздела сохранены.")
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
        pets_menu,
        func=empty_filter,
        button="pets",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        max_egg_level_menu,
        func=empty_filter,
        button="pets/max_level",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        save_max_egg_level,
        func=empty_filter,
        button=r"pets/max_level/[1-6]",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        hatch_batches_menu,
        func=empty_filter,
        button="pets/batches",
        is_private=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        change_hatch_batch_count,
        func=empty_filter,
        button=r"pets/batches/[1-6]/(minus|plus)",
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
