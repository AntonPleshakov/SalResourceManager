from dataclasses import dataclass

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message, CallbackQuery

from resources.user_data import UserData
from tg.user_data.common import value_input_hint
from tg.user_data.editing_common import (
    FillState,
    account_line,
    format_field_input_value,
)
from tg.utils import Button, get_ids


Update = Message | CallbackQuery


@dataclass(frozen=True)
class FillContext:
    state: FillState
    current_user: UserData


def fill_prompt(
    context: FillContext,
    error: str = "",
    notice: str = "",
) -> str:
    state = context.state
    field = state.current_field
    current_value = format_field_input_value(
        field,
        context.current_user.get_value(field.name),
    )
    error_line = f"⚠️ {error}\n\n" if error else ""
    notice_line = f"{notice}\n\n" if notice else ""
    return (
        f"{notice_line}"
        f"<b>{field.title}</b>\n"
        f"<i>Шаг {state.index + 1} из {len(state.fields)}</i>\n\n"
        f"{account_line(state.account_tag)}"
        f"{error_line}"
        f"Сохранено сейчас: <b>{current_value}</b>\n\n"
        "Отправьте новое значение — оно сохранится сразу.\n"
        f"{value_input_hint(field)}\n\n"
        "Чтобы ничего не менять, нажмите «Пропустить»."
    )


def fill_keyboard(state: FillState) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup()
    step_buttons = []
    if state.index > 0:
        step_buttons.append(
            Button("⬅️ Назад", "user_data/fill/back").inline()
        )
    step_buttons.append(
        Button("⏭ Пропустить", "user_data/fill/skip").inline()
    )
    keyboard.row(*step_buttons)
    keyboard.row(
        Button("✅ Закончить сейчас", "user_data/fill/finish").inline()
    )
    return keyboard


def show_fill_step(
    update: Update,
    bot: TeleBot,
    context: FillContext,
    error: str = "",
    notice: str = "",
) -> None:
    chat_id = get_ids(update)[1]
    bot.edit_message_text(
        fill_prompt(context, error, notice),
        chat_id,
        context.state.prompt_message_id,
        reply_markup=fill_keyboard(context.state),
    )
