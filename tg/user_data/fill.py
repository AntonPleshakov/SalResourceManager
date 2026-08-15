from dataclasses import dataclass

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

import resources.user_data as user_data_resources
from logger.app_logger import logger
import tg.user_data as user_data
from tg.user_data.common import get_active_user_or_prompt, value_input_hint
from tg.user_data.editing_common import (
    EditUserDataStates,
    FILL_SECTIONS,
    FillState,
    PRIVATE_CALLBACK_HANDLER,
    PRIVATE_TEXT_HANDLER,
    VALUE_EDIT_SECTIONS,
    account_line,
    format_field_value,
    load_state,
    save_state,
)
from tg.metrics import record_resource_update
from tg.utils import Button, get_ids, get_username


FILL_STATE_KEY = "fill_state"
Update = Message | CallbackQuery


@dataclass(frozen=True)
class FillContext:
    state: FillState
    current_user: user_data_resources.UserData


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


def _fill_prompt(context: FillContext, error: str = "") -> str:
    state = context.state
    field = state.current_field
    current_value = format_field_value(
        field,
        context.current_user.get_value(field.name),
    )
    error_line = f"⚠️ {error}\n\n" if error else ""
    return (
        f"<b>Заполнение: {state.config.title} "
        f"({state.index + 1}/{len(state.fields)})</b>\n\n"
        f"{account_line(state.account_tag)}"
        f"{error_line}"
        f"Текущее значение: <b>{current_value}</b>\n\n"
        f"Введите значение для «{field.title}».\n"
        f"{value_input_hint(field)}\n\n"
        "Чтобы оставить текущее значение без изменений, нажмите «Пропустить»."
    )


def _fill_keyboard(state: FillState) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button("⏭ Пропустить", "user_data/fill/skip").inline(),
        Button("✅ Закончить", state.config.finish_callback).inline(),
    )
    return keyboard


def _show_fill_step(
    update: Update,
    bot: TeleBot,
    context: FillContext,
    error: str = "",
) -> None:
    _, chat_id, _ = get_ids(update)
    bot.edit_message_text(
        _fill_prompt(context, error),
        chat_id,
        context.state.prompt_message_id,
        reply_markup=_fill_keyboard(context.state),
    )


def _stop_fill(
    update: Update,
    bot: TeleBot,
    log_reason: str,
    user_message: str,
) -> None:
    user_id, chat_id, _ = get_ids(update)
    logger.warning(
        "%s for user_id=%s username=%s",
        log_reason,
        user_id,
        get_username(update),
    )
    bot.delete_state(user_id)
    bot.send_message(chat_id, user_message)


def _load_fill_context(update: Update, bot: TeleBot) -> FillContext | None:
    user_id, _, _ = get_ids(update)
    state = load_state(bot, user_id, FILL_STATE_KEY, FillState)
    if state is None:
        _stop_fill(
            update,
            bot,
            "Invalid section fill state",
            "Не удалось продолжить заполнение. Откройте раздел заново.",
        )
        return None

    current_user = user_data.get_user_data_db().get_user(
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
    user_id, _, _ = get_ids(message)
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


def _complete_fill(update: Update, bot: TeleBot, state: FillState) -> None:
    user_id, chat_id, _ = get_ids(update)
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
    bot.edit_message_text(
        "✅ Заполнение завершено. Введённые значения сохранены, "
        "пропущенные не изменены.",
        chat_id,
        state.prompt_message_id,
        reply_markup=keyboard,
    )


def _advance_fill(
    update: Update,
    bot: TeleBot,
    context: FillContext,
) -> None:
    if context.state.is_last_step:
        _complete_fill(update, bot, context.state)
        return

    next_state = context.state.next_step()
    user_id, _, _ = get_ids(update)
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
    )


def _start_fill(
    callback_query: CallbackQuery,
    bot: TeleBot,
    section: str,
    fields: tuple[user_data_resources.ResourceField, ...],
) -> None:
    user_id, _, message_id = get_ids(callback_query)
    current_user = get_active_user_or_prompt(
        callback_query,
        bot,
        FILL_SECTIONS[section].finish_callback,
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
    value = _parse_fill_value(message, bot, context)
    if value is None:
        return
    current_user = _persist_fill_value(message, bot, context, value)
    if current_user is None:
        return
    _advance_fill(
        message,
        bot,
        FillContext(state=context.state, current_user=current_user),
    )


def skip_fill_value(callback_query: CallbackQuery, bot: TeleBot) -> None:
    context = _load_fill_context(callback_query, bot)
    if context is not None:
        _advance_fill(callback_query, bot, context)


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        fill_section,
        button=r"user_data/fill/(resources|technologies)",
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_callback_query_handler(
        fill_tracked_fields,
        button=r"user_data/fill/tracked/[0-9,]+",
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_callback_query_handler(
        skip_fill_value,
        button="user_data/fill/skip",
        state=EditUserDataStates.fill_values,
        **PRIVATE_CALLBACK_HANDLER,
    )
    bot.register_message_handler(
        save_fill_value,
        state=EditUserDataStates.fill_values,
        **PRIVATE_TEXT_HANDLER,
    )
