from html import escape
from typing import Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from logger.app_logger import logger
from resources.egg_levels import EGG_LEVELS, EggLevel, format_hatch_batch_count
from resources.user_data import UserData
import tg.user_data as user_data
from tg.metrics import record_resource_update
from tg.handlers import HandlerRegistry
from tg.rich import (
    button_row,
    callback_button,
    edit_rich_message,
    input_rich_message,
)
from tg.user_data.common import (
    MenuContent,
    deliver_menu,
    get_active_user_or_prompt,
)
from tg.utils import get_ids, get_username


def build_pets_menu(user: UserData, notice: str = "") -> MenuContent:
    max_level = EggLevel(user.max_egg_level.value)
    batch_lines = []
    total_batches = 0
    for level in reversed(EGG_LEVELS):
        if level > max_level:
            continue
        count = getattr(user, level.batch_field_name).value
        total_batches += count
        if count:
            batch_lines.append(
                "<tr>"
                f"<td>{escape(level.label)}</td>"
                f'<td align="right"><b>{count}</b></td>'
                "</tr>"
            )
    parts = []
    if notice:
        parts.append(f"<blockquote>{notice}</blockquote>")
    parts.extend(
        (
            "<h2>Питомцы</h2>",
            "<p>Игровой аккаунт: "
            f"<b>{escape(str(user.tag.value))}</b></p>",
            '<table bordered compact><caption>Настройки</caption>',
            "<tr><td>Яиц в одном пакете</td>"
            f'<td align="right"><b>{user.eggs_per_hatch_batch.value}</b></td></tr>',
            "<tr><td>Максимальный уровень яйца</td>"
            f'<td align="right"><b>{escape(max_level.label)}</b></td></tr>',
            "<tr><td>Пакетов в день</td>"
            f'<td align="right"><b>{total_batches}</b></td></tr>',
            "</table>",
        )
    )
    if batch_lines:
        parts.extend(
            (
                '<table bordered compact><caption>Пакеты по уровням</caption>',
                *batch_lines,
                "</table>",
            )
        )
    else:
        parts.append("<p><i>Пакеты по уровням пока не настроены.</i></p>")
    parts.extend(
        (
            button_row(
                (
                    callback_button(
                        "🥚 Яиц в пакете",
                        "user_data/edit/eggs_per_hatch_batch",
                    ),
                    callback_button("🏆 Макс. уровень", "pets/max_level"),
                )
            ),
            button_row(
                (
                    callback_button(
                        "📅 Пакеты в день",
                        "pets/batches",
                        style="primary",
                    ),
                    callback_button("🔄 Аккаунт", "accounts/pets"),
                )
            ),
            button_row(
                (callback_button("⬅️ Назад в меню", "home"),),
                align="left",
            ),
        )
    )
    return MenuContent(rich_message=input_rich_message(parts))


def pets_menu(
    update: Union[Message, CallbackQuery], bot: TeleBot, notice: str = ""
) -> None:
    user_id = get_ids(update)[0]
    username = get_username(update)
    bot.delete_state(user_id)
    user = get_active_user_or_prompt(update, bot)
    if user is None:
        return
    content = build_pets_menu(user, notice)

    logger.debug(
        "Opening pet settings for user_id=%s username=%s", user_id, username
    )
    deliver_menu(update, bot, content)


def max_egg_level_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    chat_id, message_id = get_ids(callback_query)[1:]
    user = get_active_user_or_prompt(callback_query, bot)
    if user is None:
        return
    current_level = EggLevel(user.max_egg_level.value)
    level_buttons = []
    for level in reversed(EGG_LEVELS):
        marker = " ✓" if level == current_level else ""
        level_buttons.append(
            callback_button(
                f"{level.label}{marker}",
                f"pets/max_level/{level.value}",
                style="primary" if level == current_level else None,
            )
        )
    parts = [
        "<h2>Максимальный уровень яйца</h2>",
        "<p>Выберите самый высокий доступный уровень.</p>",
    ]
    for index in range(0, len(level_buttons), 2):
        parts.append(button_row(level_buttons[index : index + 2]))
    parts.append(
        button_row(
            (callback_button("⬅️ Назад к питомцам", "pets"),),
            align="left",
        )
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
    )


def _selected_egg_level(callback_query: CallbackQuery, bot: TeleBot):
    try:
        return EggLevel(int(callback_query.data.rsplit("/", maxsplit=1)[-1]))
    except ValueError:
        bot.answer_callback_query(
            callback_query.id, "Уровень яйца не найден", show_alert=True
        )
        return None


def _cleared_batch_counts(user, level: EggLevel):
    return [
        (candidate, getattr(user, candidate.batch_field_name).value)
        for candidate in EGG_LEVELS
        if candidate > level
        and getattr(user, candidate.batch_field_name).value > 0
    ]


def _apply_max_egg_level(
    callback_query: CallbackQuery, bot: TeleBot, level: EggLevel
) -> None:
    user_id = get_ids(callback_query)[0]
    user = get_active_user_or_prompt(callback_query, bot)
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
    record_resource_update("pets", "max_egg_level")
    pets_menu(
        callback_query,
        bot,
        f"✅ Максимальный уровень: <b>{level.label}</b> — сохранён.",
    )


def save_max_egg_level(callback_query: CallbackQuery, bot: TeleBot) -> None:
    level = _selected_egg_level(callback_query, bot)
    if level is None:
        return

    user = get_active_user_or_prompt(callback_query, bot)
    if user is None:
        return
    cleared_batches = _cleared_batch_counts(user, level)
    if level < EggLevel(user.max_egg_level.value) and cleared_batches:
        chat_id, message_id = get_ids(callback_query)[1:]
        cleared_items = "".join(
            f"<li>{escape(candidate.label)}: "
            f"<b>{format_hatch_batch_count(count)}</b></li>"
            for candidate, count in reversed(cleared_batches)
        )
        edit_rich_message(
            bot,
            chat_id,
            message_id,
            input_rich_message(
                (
                    "<h2>Понизить максимальный уровень яйца?</h2>",
                    f"<p>Новый уровень: <b>{escape(level.label)}</b></p>",
                    "<p>Будут обнулены настройки пакетов более высоких "
                    f"уровней:</p><ul>{cleared_items}</ul>",
                    "<blockquote>Это действие нельзя отменить.</blockquote>",
                    button_row(
                        (
                            callback_button(
                                "⚠️ Понизить и обнулить",
                                f"pets/max_level/confirm/{level.value}",
                                style="danger",
                            ),
                            callback_button("✖️ Отмена", "pets/max_level"),
                        )
                    ),
                )
            ),
        )
        return

    _apply_max_egg_level(callback_query, bot, level)


def confirm_max_egg_level(callback_query: CallbackQuery, bot: TeleBot) -> None:
    level = _selected_egg_level(callback_query, bot)
    if level is None:
        return
    _apply_max_egg_level(callback_query, bot, level)


def hatch_batches_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    chat_id, message_id = get_ids(callback_query)[1:]
    user = get_active_user_or_prompt(callback_query, bot)
    if user is None:
        return
    max_level = EggLevel(user.max_egg_level.value)
    total_batches = sum(
        getattr(user, level.batch_field_name).value
        for level in EGG_LEVELS
        if level <= max_level
    )
    parts = [
        "<h2>Пакеты для вылупления в день</h2>",
        "<p>Укажите максимальное количество пакетов каждого уровня. "
        "Изменения сохраняются сразу.</p>",
    ]
    for level in reversed(EGG_LEVELS):
        if level > max_level:
            continue
        count = getattr(user, level.batch_field_name).value
        parts.append(
            button_row(
                (
                    callback_button(
                        "−", f"pets/batches/{level.value}/minus"
                    ),
                    callback_button(
                        f"{level.label}: {count}", "pets/batches"
                    ),
                    callback_button(
                        "+", f"pets/batches/{level.value}/plus"
                    ),
                )
            )
        )
    parts.extend(
        (
            f"<p>Всего в день: <b>{total_batches}</b></p>",
            button_row(
                (callback_button("✅ Готово", "pets", style="success"),)
            ),
        )
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
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

    user_id = get_ids(callback_query)[0]
    username = get_username(callback_query)
    user = get_active_user_or_prompt(callback_query, bot)
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
    record_resource_update("pets", level.batch_field_name)
    hatch_batches_menu(callback_query, bot)


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.private_callback(
        pets_menu,
        button="pets",
    )
    handlers.private_callback(
        max_egg_level_menu,
        button="pets/max_level",
    )
    handlers.private_callback(
        save_max_egg_level,
        button=r"pets/max_level/[1-6]",
    )
    handlers.private_callback(
        confirm_max_egg_level,
        button=r"pets/max_level/confirm/[1-6]",
    )
    handlers.private_callback(
        hatch_batches_menu,
        button="pets/batches",
    )
    handlers.private_callback(
        change_hatch_batch_count,
        button=r"pets/batches/[1-6]/(minus|plus)",
    )
