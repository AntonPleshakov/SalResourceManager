from typing import Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from logger.app_logger import logger
from resources.egg_levels import EGG_LEVELS, EggLevel
from resources.user_data import PET_SETTINGS_FIELDS
import tg.user_data as user_data
from tg.user_data.common import get_active_user_or_prompt
from tg.utils import Button, empty_filter, get_ids, get_username


def pets_menu(
    message: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    username = get_username(message)
    bot.delete_state(user_id)
    user = get_active_user_or_prompt(message, bot, "pets")
    if user is None:
        return
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
        "<b>Питомцы</b>\n"
        f"Игровой аккаунт: <b>{formatting.escape_html(user.tag.value)}</b>\n\n"
        f"Яиц в одном пакете: <b>{user.eggs_per_hatch_batch.value}</b>\n"
        f"Максимальный уровень яйца: <b>{max_level.label}</b>\n"
        f"Пакетов в день: <b>{total_batches}</b>\n{batches}\n\n"
        "Выберите параметр для изменения."
    )
    if notice:
        text = f"{notice}\n\n{text}"

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Сменить игровой аккаунт", "accounts/pets").inline())
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
        "Opening pet settings for user_id=%s username=%s", user_id, username
    )
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def max_egg_level_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = get_active_user_or_prompt(callback_query, bot, "pets")
    if user is None:
        return
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

    user = get_active_user_or_prompt(callback_query, bot, "pets")
    if user is None:
        return
    values = {"max_egg_level": level.value}
    values.update(
        {
            candidate.batch_field_name: 0
            for candidate in EGG_LEVELS
            if candidate > level
        }
    )
    user_data.get_user_data_db().set_values(
        user_id,
        get_username(callback_query),
        values,
        account_id=user.account_id.value,
    )
    pets_menu(
        callback_query,
        bot,
        f"✅ Максимальный уровень: <b>{level.label}</b> — сохранён.",
    )


def hatch_batches_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    user = get_active_user_or_prompt(callback_query, bot, "pets")
    if user is None:
        return
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
            Button(f"{level.label}: {count}", "pets/batches").inline(),
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
    user = get_active_user_or_prompt(callback_query, bot, "pets")
    if user is None:
        return
    if level > EggLevel(user.max_egg_level.value):
        bot.answer_callback_query(
            callback_query.id,
            "Сначала повысьте максимальный уровень яйца",
            show_alert=True,
        )
        return
    current = getattr(user, level.batch_field_name).value
    user_data.get_user_data_db().set_value(
        user_id,
        username,
        level.batch_field_name,
        max(0, current + delta),
        account_id=user.account_id.value,
    )
    hatch_batches_menu(callback_query, bot)


def register_handlers(bot: TeleBot) -> None:
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
