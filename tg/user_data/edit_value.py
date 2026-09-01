from telebot import TeleBot, formatting
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import resources.user_data as user_data_resources
from logger.app_logger import logger
import tg.user_data as user_data
from tg.metrics import record_resource_update
from tg.user_data.common import get_active_user_or_prompt, value_input_hint
from tg.user_data.editing_common import (
    EditUserDataStates,
    PRIVATE_CALLBACK_HANDLER,
    PRIVATE_TEXT_HANDLER,
    VALUE_EDIT_SECTIONS,
    ValueEditState,
    account_line,
    format_field_value,
    load_state,
    save_state,
)
from tg.utils import Button, get_ids, get_username


VALUE_STATE_KEY = "value_edit_state"


def _reject_unknown_field(
    callback_query: CallbackQuery, bot: TeleBot, field_name: str
) -> None:
    logger.warning(
        "Unknown user data field requested by user_id=%s username=%s field=%s",
        callback_query.from_user.id,
        get_username(callback_query),
        field_name,
    )
    bot.answer_callback_query(callback_query.id, "Показатель не найден")


def _show_value_prompt(
    callback_query: CallbackQuery,
    bot: TeleBot,
    state: ValueEditState,
    current_user: user_data_resources.UserData,
) -> None:
    chat_id, message_id = get_ids(callback_query)[1:]
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("✖️ Отмена", state.section).inline())
    current_value = format_field_value(
        state.field,
        current_user.get_value(state.field_name),
    )
    bot.edit_message_text(
        f"{account_line(current_user.tag.value)}"
        f"Текущее значение: <b>{current_value}</b>\n\n"
        f"Введите новое значение для «{state.field.title}».\n"
        f"{value_input_hint(state.field)}",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def _stop_invalid_edit(message: Message, bot: TeleBot) -> None:
    user_id, chat_id = get_ids(message)[:2]
    logger.warning(
        "Invalid edit state for user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    bot.delete_state(user_id)
    bot.send_message(
        chat_id,
        "Не удалось определить редактируемый показатель. "
        "Откройте раздел заново.",
    )


def _reply_value_error(
    message: Message,
    bot: TeleBot,
    state: ValueEditState,
    error: ValueError,
    *,
    show_hint: bool = False,
) -> None:
    hint = f"\n{value_input_hint(state.field)}" if show_hint else ""
    escaped_error = formatting.escape_html(str(error))
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("✖️ Отмена", state.section).inline())
    bot.edit_message_text(
        f"⚠️ Значение для «{state.field.title}» не подходит: "
        f"{escaped_error}\n\n"
        f"Отправьте новое значение.{hint}",
        get_ids(message)[1],
        state.prompt_message_id,
        reply_markup=keyboard,
    )


def _parse_value(
    message: Message, bot: TeleBot, state: ValueEditState
) -> int | None:
    try:
        return user_data_resources.parse_editable_field_value(
            state.field_name,
            message.text,
        )
    except ValueError as error:
        logger.info(
            "Invalid user data input user_id=%s username=%s field=%s",
            message.from_user.id,
            get_username(message),
            state.field_name,
        )
        _reply_value_error(message, bot, state, error, show_hint=True)
        return None


def _persist_value(
    message: Message,
    bot: TeleBot,
    state: ValueEditState,
    value: int,
) -> user_data_resources.UserData | None:
    user_id = get_ids(message)[0]
    try:
        updated_user = user_data.get_user_data_db().set_value(
            user_id,
            get_username(message),
            state.field_name,
            value,
            account_id=state.account_id,
        )
        record_resource_update(state.section, state.field_name)
        return updated_user
    except ValueError as error:
        logger.warning(
            "Rejected user data value user_id=%s username=%s field=%s reason=%s",
            user_id,
            get_username(message),
            state.field_name,
            error,
        )
        _reply_value_error(message, bot, state, error)
        return None


def _open_section(
    message: Message,
    bot: TeleBot,
    state: ValueEditState,
    current_user: user_data_resources.UserData,
    notice: str,
) -> None:
    menu_builders = {
        "resources": user_data.resources.build_resources_menu,
        "technologies": user_data.technologies.build_technologies_menu,
        "pets": user_data.pets.build_pets_menu,
    }
    user_id, chat_id = get_ids(message)[:2]
    bot.delete_state(user_id)
    content = menu_builders[state.section](current_user, notice)
    bot.edit_message_text(
        content.text,
        chat_id,
        state.prompt_message_id,
        reply_markup=content.keyboard,
    )


def _delete_registered_input(message: Message, bot: TeleBot) -> None:
    _, chat_id, message_id = get_ids(message)
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException as error:
        logger.warning(
            "Unable to delete registered value input chat_id=%s "
            "message_id=%s reason=%s",
            chat_id,
            message_id,
            error,
        )


def request_value(callback_query: CallbackQuery, bot: TeleBot) -> None:
    field_name = callback_query.data.rsplit("/", maxsplit=1)[-1]
    if field_name not in VALUE_EDIT_SECTIONS:
        _reject_unknown_field(callback_query, bot, field_name)
        return

    user_id, _, message_id = get_ids(callback_query)
    current_user = get_active_user_or_prompt(
        callback_query,
        bot,
    )
    state = ValueEditState(
        field_name=field_name,
        account_id=current_user.account_id.value,
        prompt_message_id=message_id,
    )
    logger.info(
        "User data edit started user_id=%s username=%s field=%s",
        user_id,
        get_username(callback_query),
        field_name,
    )
    bot.set_state(user_id, EditUserDataStates.value)
    save_state(bot, user_id, VALUE_STATE_KEY, state)
    _show_value_prompt(callback_query, bot, state, current_user)


def save_value(message: Message, bot: TeleBot) -> None:
    user_id = get_ids(message)[0]
    state = load_state(bot, user_id, VALUE_STATE_KEY, ValueEditState)
    if state is None:
        _stop_invalid_edit(message, bot)
        return

    value = _parse_value(message, bot, state)
    if value is None:
        return
    current_user = _persist_value(message, bot, state, value)
    if current_user is None:
        return

    logger.info(
        "User data edit completed user_id=%s username=%s field=%s",
        user_id,
        get_username(message),
        state.field_name,
    )
    displayed_value = format_field_value(state.field, value)
    _delete_registered_input(message, bot)
    _open_section(
        message,
        bot,
        state,
        current_user,
        f"✅ {state.field.title}: <b>{displayed_value}</b> — значение зарегистрировано.",
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        request_value,
        button=r"user_data/edit/[a-z_]+",
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_message_handler(
        save_value,
        state=EditUserDataStates.value,
        **PRIVATE_TEXT_HANDLER,
    )
