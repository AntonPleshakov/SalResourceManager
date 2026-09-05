from telebot import TeleBot, formatting
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import resources.user_data as user_data_resources
from logger.app_logger import logger
import tg.user_data as user_data
from tg.user_data.common import get_active_user_or_prompt
from tg.user_data.editing_common import (
    EditUserDataStates,
    FILL_SECTIONS,
    FillState,
    VALUE_EDIT_SECTIONS,
    account_line,
    format_field_value,
    load_state,
    save_state,
)
from tg.user_data.fill_view import FillContext, show_fill_step as _show_fill_step
from tg.user_data.fill_handlers import register_handlers
from tg.metrics import record_resource_update
from tg.utils import Button, get_ids, get_username


FILL_STATE_KEY = "fill_state"
Update = Message | CallbackQuery


def _decode_tracked_fields(
    encoded_indexes: str,
) -> tuple[user_data_resources.ResourceField, ...] | None:
    try:
        indexes = {int(value) for value in encoded_indexes.split(",")}
    except ValueError:
        return None
    if not indexes or any(
        index < 0 or index >= len(user_data_resources.TRACKED_FIELDS)
        for index in indexes
    ):
        return None
    return tuple(
        field
        for index, field in enumerate(user_data_resources.TRACKED_FIELDS)
        if index in indexes
    )


def _stop_fill(
    update: Update,
    bot: TeleBot,
    log_reason: str,
    user_message: str,
) -> None:
    user_id, chat_id = get_ids(update)[:2]
    logger.warning(
        "%s for user_id=%s username=%s",
        log_reason,
        user_id,
        get_username(update),
    )
    bot.delete_state(user_id)
    bot.send_message(chat_id, user_message)


def _load_fill_context(update: Update, bot: TeleBot) -> FillContext | None:
    user_id = get_ids(update)[0]
    state = load_state(bot, user_id, FILL_STATE_KEY, FillState)
    if state is None:
        _stop_fill(
            update,
            bot,
            "Invalid section fill state",
            "Не удалось продолжить заполнение. Откройте раздел заново.",
        )
        return None

    current_user = user_data.get_user_data_db().get_assigned_user(
        user_id,
        state.account_id,
    )
    if current_user is None:
        _stop_fill(
            update,
            bot,
            f"Fill account not found account_id={state.account_id}",
            "Игровой аккаунт не найден. Откройте раздел заново.",
        )
        return None
    return FillContext(state=state, current_user=current_user)


def _show_fill_error(
    update: Update,
    bot: TeleBot,
    context: FillContext,
    error: ValueError,
) -> None:
    escaped_error = formatting.escape_html(str(error))
    _show_fill_step(
        update,
        bot,
        context,
        f"Значение не подходит: {escaped_error}",
    )


def _parse_fill_value(
    message: Message,
    bot: TeleBot,
    context: FillContext,
) -> int | None:
    field = context.state.current_field
    try:
        return user_data_resources.parse_editable_field_value(
            field.name,
            message.text,
        )
    except ValueError as error:
        logger.info(
            "Invalid section input user_id=%s username=%s section=%s field=%s",
            message.from_user.id,
            get_username(message),
            context.state.section,
            field.name,
        )
        _show_fill_error(message, bot, context, error)
        return None


def _persist_fill_value(
    message: Message,
    bot: TeleBot,
    context: FillContext,
    value: int,
) -> user_data_resources.UserData | None:
    user_id = get_ids(message)[0]
    field = context.state.current_field
    try:
        updated_user = user_data.get_user_data_db().set_value(
            user_id,
            get_username(message),
            field.name,
            value,
            account_id=context.state.account_id,
        )
        category = VALUE_EDIT_SECTIONS.get(field.name, context.state.section)
        record_resource_update(category, field.name)
        return updated_user
    except ValueError as error:
        logger.warning(
            "Rejected user data value user_id=%s username=%s section=%s "
            "field=%s reason=%s",
            user_id,
            get_username(message),
            context.state.section,
            field.name,
            error,
        )
        _show_fill_error(message, bot, context, error)
        return None


def _complete_fill(
    update: Update,
    bot: TeleBot,
    state: FillState,
    notice: str = "",
) -> None:
    user_id, chat_id = get_ids(update)[:2]
    bot.delete_state(user_id)
    logger.info(
        "User data section fill completed user_id=%s username=%s "
        "section=%s fields=%d",
        user_id,
        get_username(update),
        state.section,
        len(state.fields),
    )
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button(
            f"⬅️ {state.config.finish_button}",
            state.config.finish_callback,
        ).inline()
    )
    notice_line = f"{notice}\n\n" if notice else ""
    bot.edit_message_text(
        f"{notice_line}"
        f"<b>Заполнение завершено</b>\n\n"
        f"{account_line(state.account_tag)}"
        "Все введённые значения зарегистрированы. "
        "Пропущенные показатели не изменены.",
        chat_id,
        state.prompt_message_id,
        reply_markup=keyboard,
    )


def _advance_fill(
    update: Update,
    bot: TeleBot,
    context: FillContext,
    notice: str = "",
) -> None:
    if context.state.is_last_step:
        _complete_fill(update, bot, context.state, notice)
        return

    next_state = context.state.next_step()
    user_id = get_ids(update)[0]
    logger.debug(
        "User data section fill progress user_id=%s username=%s "
        "section=%s step=%d/%d",
        user_id,
        get_username(update),
        next_state.section,
        next_state.index,
        len(next_state.fields),
    )
    save_state(bot, user_id, FILL_STATE_KEY, next_state)
    _show_fill_step(
        update,
        bot,
        FillContext(state=next_state, current_user=context.current_user),
        notice=notice,
    )


def _delete_input_message(message: Message, bot: TeleBot) -> None:
    _, chat_id, message_id = get_ids(message)
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException as error:
        logger.warning(
            "Unable to delete fill input chat_id=%s "
            "message_id=%s reason=%s",
            chat_id,
            message_id,
            error,
        )


def _start_fill(
    callback_query: CallbackQuery,
    bot: TeleBot,
    section: str,
    fields: tuple[user_data_resources.ResourceField, ...],
) -> None:
    user_id, message_id = get_ids(callback_query)[::2]
    current_user = get_active_user_or_prompt(
        callback_query,
        bot,
    )
    state = FillState.start(section, fields, current_user, message_id)
    logger.info(
        "User data fill started user_id=%s username=%s section=%s fields=%s",
        user_id,
        get_username(callback_query),
        section,
        ",".join(state.field_names),
    )
    bot.set_state(user_id, EditUserDataStates.fill_values)
    save_state(bot, user_id, FILL_STATE_KEY, state)
    _show_fill_step(
        callback_query,
        bot,
        FillContext(state=state, current_user=current_user),
    )


def fill_section(callback_query: CallbackQuery, bot: TeleBot) -> None:
    section = callback_query.data.rsplit("/", maxsplit=1)[-1]
    config = FILL_SECTIONS.get(section)
    if config is None or config.fields is None:
        logger.warning(
            "Unknown user data section requested by user_id=%s "
            "username=%s section=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            section,
        )
        bot.answer_callback_query(callback_query.id, "Раздел не найден")
        return
    _start_fill(callback_query, bot, section, config.fields)


def fill_tracked_fields(callback_query: CallbackQuery, bot: TeleBot) -> None:
    encoded_indexes = callback_query.data.rsplit("/", maxsplit=1)[-1]
    fields = _decode_tracked_fields(encoded_indexes)
    if fields is None:
        logger.warning(
            "Invalid tracked fields requested by user_id=%s username=%s "
            "indexes=%s",
            callback_query.from_user.id,
            get_username(callback_query),
            encoded_indexes,
        )
        bot.answer_callback_query(callback_query.id, "Показатели не найдены")
        return
    _start_fill(callback_query, bot, "reminder", fields)


def save_fill_value(message: Message, bot: TeleBot) -> None:
    context = _load_fill_context(message, bot)
    if context is None:
        return
    _delete_input_message(message, bot)
    value = _parse_fill_value(message, bot, context)
    if value is None:
        return
    current_user = _persist_fill_value(message, bot, context, value)
    if current_user is None:
        return
    field = context.state.current_field
    displayed_value = format_field_value(field, value)
    _advance_fill(
        message,
        bot,
        FillContext(state=context.state, current_user=current_user),
        f"✅ {field.title}: <b>{displayed_value}</b> — значение зарегистрировано.",
    )


def skip_fill_value(callback_query: CallbackQuery, bot: TeleBot) -> None:
    context = _load_fill_context(callback_query, bot)
    if context is not None:
        _advance_fill(callback_query, bot, context)
