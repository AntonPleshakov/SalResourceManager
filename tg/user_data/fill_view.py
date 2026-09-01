from dataclasses import dataclass

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message, CallbackQuery

from resources.user_data import UserData
from tg.user_data.common import value_input_hint
from tg.user_data.editing_common import (
    FillState,
    account_line,
    format_field_value,
)
from tg.utils import Button, get_ids


Update = Message | CallbackQuery


@dataclass(frozen=True)
class FillContext:
    state: FillState
    current_user: UserData


def fill_prompt(context: FillContext, error: str = "") -> str:
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


def fill_keyboard(state: FillState) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button("⏭ Пропустить", "user_data/fill/skip").inline(),
        Button("✅ Закончить", state.config.finish_callback).inline(),
    )
    return keyboard


def show_fill_step(
    update: Update,
    bot: TeleBot,
    context: FillContext,
    error: str = "",
) -> None:
    chat_id = get_ids(update)[1]
    bot.edit_message_text(
        fill_prompt(context, error),
        chat_id,
        context.state.prompt_message_id,
        reply_markup=fill_keyboard(context.state),
    )
