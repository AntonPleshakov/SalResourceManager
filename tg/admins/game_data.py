"""Administrative game-data report export."""

from html import escape
from time import monotonic
from typing import Iterable, Sequence

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
)

from db.initializer import get_user_data_db
from logger.app_logger import logger
from reports.game_data import GameDataReport
from resources.user_data import UserData
from tg.admins.common import get_active_admin_group
from tg.metrics import APPLICATION_METRICS
from tg.utils import Button, empty_filter, get_ids, get_username


_GOOGLE_EXPORT_BUTTON = "admins/game_data/google"
_IDENTITY_COLUMNS = 4
_MAX_TABLE_COLUMNS = 20
_MAX_RICH_MESSAGE_BYTES = 30_000
_MAX_RICH_MESSAGE_BLOCKS = 500


def _table_column_groups(column_count: int) -> list[list[int]]:
    identity_columns = list(range(min(_IDENTITY_COLUMNS, column_count)))
    data_columns = list(range(len(identity_columns), column_count))
    data_columns_per_table = _MAX_TABLE_COLUMNS - len(identity_columns)
    if not data_columns:
        return [identity_columns]
    return [
        identity_columns + data_columns[start : start + data_columns_per_table]
        for start in range(0, len(data_columns), data_columns_per_table)
    ]


def _render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    columns: Sequence[int],
    caption: str,
) -> str:
    header = "".join(
        f"<th>{escape(str(headers[index]))}</th>" for index in columns
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td align="right">{escape(str(row[index]))}</td>'
            if str(row[index]).lstrip("-").isdigit()
            else f"<td>{escape(str(row[index]))}</td>"
            for index in columns
        )
        + "</tr>"
        for row in rows
    )
    return (
        "<table bordered striped compact>"
        f"<caption>{escape(caption)}</caption>"
        f"<tr>{header}</tr>{body}</table>"
    )


def _render_game_data_html(
    clan_title: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    total_rows: int,
) -> str:
    column_groups = _table_column_groups(len(headers))
    parts = [
        "<h2>Игровые данные</h2>",
        f"<p>Клан: <b>{escape(clan_title)}</b>. Аккаунтов: {total_rows}.</p>",
    ]
    if not rows:
        if total_rows:
            parts.append(
                "<p>Предпросмотр не помещается в сообщение. "
                "Экспортируйте полные данные в Google.</p>"
            )
        else:
            parts.append("<p>В клане пока нет игровых аккаунтов.</p>")
        return "".join(parts)

    for index, columns in enumerate(column_groups, start=1):
        caption = f"Поля {index} из {len(column_groups)}"
        parts.append(_render_table(headers, rows, columns, caption))
    if len(rows) < total_rows:
        parts.append(
            "<footer>"
            f"Показано {len(rows)} из {total_rows} аккаунтов. "
            "В Google экспортируются все данные."
            "</footer>"
        )
    return "".join(parts)


def build_game_data_message(
    clan_title: str, users: Iterable[UserData]
) -> InputRichMessage:
    report_rows = GameDataReport.build_rows(users)
    headers, rows = report_rows[0], report_rows[1:]
    column_groups = _table_column_groups(len(headers))
    non_row_blocks = 3 + len(column_groups)
    max_rows = max(
        0,
        (_MAX_RICH_MESSAGE_BLOCKS - non_row_blocks) // len(column_groups) - 1,
    )
    visible_rows = rows[:max_rows]
    html = _render_game_data_html(
        clan_title, headers, visible_rows, len(rows)
    )
    while visible_rows and len(html.encode("utf-8")) > _MAX_RICH_MESSAGE_BYTES:
        visible_rows.pop()
        html = _render_game_data_html(
            clan_title, headers, visible_rows, len(rows)
        )
    return InputRichMessage(html=html, skip_entity_detection=True)


def _preview_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        Button("📤 Экспортировать в Google", _GOOGLE_EXPORT_BUTTON).inline()
    )
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    return keyboard


def _exported_keyboard(url: str) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("📊 Открыть Google Таблицу", url=url))
    keyboard.add(Button("🔄 Обновить данные", "admins/game_data").inline())
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    return keyboard


def show_game_data(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Game data preview requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    try:
        group = get_active_admin_group(user_id)
        users = get_user_data_db().get_users(group.group_id)
        rich_message = build_game_data_message(group.title, users)
    except Exception as error:
        logger.exception(
            "Unable to build game data preview for user_id=%s: %s",
            user_id,
            error,
        )
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
        bot.edit_message_text(
            "Не удалось сформировать игровые данные. Попробуйте ещё раз позже.",
            chat_id,
            message_id,
            reply_markup=keyboard,
        )
        return

    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        rich_message=rich_message,
        reply_markup=_preview_keyboard(),
    )


def export_game_data(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Google game data export requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    started_at = monotonic()
    result = "failed"
    try:
        group = get_active_admin_group(user_id)
        url = GameDataReport().export(
            get_user_data_db().get_users(group.group_id)
        )
    except Exception as error:
        logger.exception(
            "Unable to export game data report for user_id=%s: %s",
            user_id,
            error,
        )
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось экспортировать данные в Google. Попробуйте ещё раз позже.",
            show_alert=True,
        )
        return
    else:
        result = "completed"
    finally:
        APPLICATION_METRICS.reports.labels(
            report="game_data",
            result=result,
        ).inc()
        APPLICATION_METRICS.report_duration.labels(report="game_data").observe(
            monotonic() - started_at
        )

    bot.edit_message_reply_markup(
        chat_id,
        message_id,
        reply_markup=_exported_keyboard(url),
    )
    bot.answer_callback_query(
        callback_query.id,
        "Данные экспортированы в Google.",
    )


def register_handlers(bot: TeleBot) -> None:
    bot.register_callback_query_handler(
        show_game_data,
        func=empty_filter,
        button="admins/game_data",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        export_game_data,
        func=empty_filter,
        button=_GOOGLE_EXPORT_BUTTON,
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
