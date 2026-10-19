"""Administrative game-data report export."""

from datetime import datetime
from html import escape
from time import monotonic, time
from typing import Iterable, Sequence

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
)

from common.datetime_utils import format_last_update_time
from db.initializer import get_access_group_db, get_admins_db, get_user_data_db
from logger.app_logger import logger
from reports.game_data import GameDataReport
from resources.user_data import UserData
from tg.admins.common import (
    AdminAccessError,
    require_admin_access,
)
from tg.handlers import (
    ActiveClan,
    ClanAdminContext,
    ClanFromCallback,
    HandlerRegistry,
)
from tg.metrics import APPLICATION_METRICS
from tg.utils import Button, get_ids, get_username


_GOOGLE_EXPORT_BUTTON = "admins/game_data/google"
_GOOGLE_CONNECT_BUTTON = "admins/game_data/google/connect"
_GOOGLE_CHECK_BUTTON = "admins/game_data/google/check"
_IDENTITY_COLUMNS = 2
_MAX_TABLE_COLUMNS = 8
_MAX_RICH_MESSAGE_BYTES = 30_000
_MAX_RICH_MESSAGE_BLOCKS = 500
_PREVIEW_PAGE_SIZE = 10


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
    updated_at: datetime | None,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    total_rows: int,
    page: int,
    total_pages: int,
) -> str:
    column_groups = _table_column_groups(len(headers))
    updated = format_last_update_time(updated_at)
    update_status = (
        "<p>Последнее обновление Google Таблицы:<br>"
        f"<b>{escape(updated)}</b></p>"
    )
    parts = [
        "<h2>Игровые данные</h2>",
        f"<p>Клан: <b>{escape(clan_title)}</b>. "
        f"Аккаунтов: {total_rows}. "
        f"Страница: {page + 1} из {total_pages}.</p>",
    ]
    if not rows:
        if total_rows:
            parts.append(
                "<p>Предпросмотр не помещается в сообщение. "
                "В Google Таблицу выгружаются полные данные.</p>"
            )
        else:
            parts.append("<p>В клане пока нет игровых аккаунтов.</p>")
        parts.append(update_status)
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
    parts.append(update_status)
    return "".join(parts)


def build_game_data_message(
    clan_title: str,
    users: Iterable[UserData],
    updated_at: datetime | None,
    page: int = 0,
) -> InputRichMessage:
    users = list(users)
    total_rows = len(users)
    total_pages = max(1, (total_rows + _PREVIEW_PAGE_SIZE - 1) // _PREVIEW_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    visible_users = users[
        page * _PREVIEW_PAGE_SIZE : (page + 1) * _PREVIEW_PAGE_SIZE
    ]
    report_rows = GameDataReport.build_rows(visible_users)
    headers, rows = report_rows[0], report_rows[1:]
    column_groups = _table_column_groups(len(headers))
    non_row_blocks = 4 + len(column_groups)
    max_rows = max(
        0,
        (_MAX_RICH_MESSAGE_BLOCKS - non_row_blocks) // len(column_groups) - 1,
    )
    visible_rows = rows[:max_rows]
    html = _render_game_data_html(
        clan_title,
        updated_at,
        headers,
        visible_rows,
        total_rows,
        page,
        total_pages,
    )
    while visible_rows and len(html.encode("utf-8")) > _MAX_RICH_MESSAGE_BYTES:
        visible_rows.pop()
        html = _render_game_data_html(
            clan_title,
            updated_at,
            headers,
            visible_rows,
            total_rows,
            page,
            total_pages,
        )
    return InputRichMessage(html=html, skip_entity_detection=True)


def _game_data_keyboard(
    group_id: int,
    url: str,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("📊 Открыть Google Таблицу", url=url))
    page_buttons = []
    if page > 0:
        page_buttons.append(
            Button(
                "⬅️ Предыдущая",
                f"admins/game_data/page/{page - 1}",
            ).inline()
        )
    if page + 1 < total_pages:
        page_buttons.append(
            Button(
                "Следующая ➡️",
                f"admins/game_data/page/{page + 1}",
            ).inline()
        )
    if page_buttons:
        keyboard.row(*page_buttons)
    keyboard.add(
        Button(
            "🔄 Обновить данные",
            f"{_GOOGLE_EXPORT_BUTTON}/{group_id}/{page}",
        ).inline()
    )
    keyboard.add(
        Button(
            "🔐 Сменить Google-аккаунт",
            f"{_GOOGLE_CONNECT_BUTTON}/{group_id}",
        ).inline()
    )
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    return keyboard


def _spreadsheet_updated_at(group_id: int) -> datetime | None:
    return GameDataReport().get_modified_time(group_id)


def _show_game_data_screen(
    bot: TeleBot,
    chat_id: int,
    message_id: int,
    group_id: int,
    clan_title: str,
    spreadsheet_url: str,
    page: int = 0,
) -> None:
    users = get_user_data_db().get_clan_users(group_id)
    total_pages = max(1, (len(users) + _PREVIEW_PAGE_SIZE - 1) // _PREVIEW_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        rich_message=build_game_data_message(
            clan_title,
            users,
            _spreadsheet_updated_at(group_id),
            page,
        ),
        reply_markup=_game_data_keyboard(
            group_id,
            spreadsheet_url,
            page,
            total_pages,
        ),
    )


def _show_export_waiting(bot: TeleBot, chat_id: int, message_id: int) -> None:
    bot.edit_message_text(
        "<b>Обновляем Google Таблицу…</b>\n\n"
        "Пожалуйста, подождите. Это может занять некоторое время.",
        chat_id,
        message_id,
    )


def _show_preview_waiting(bot: TeleBot, chat_id: int, message_id: int) -> None:
    bot.edit_message_text(
        "<b>Формируем предпросмотр…</b>\n\n"
        "Пожалуйста, подождите. Это может занять некоторое время.",
        chat_id,
        message_id,
    )


def _request_google_access(
    callback_query: CallbackQuery,
    bot: TeleBot,
    group_id: int,
    admins,
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    group = get_access_group_db().get_group(group_id)
    if group is None:
        raise ValueError("Клан не найден")
    spreadsheet_url = GameDataReport().prepare(group_id, group.title)
    admins.start_google_access_request(user_id, group_id, int(time()) - 5)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(
            "📊 Открыть таблицу и запросить доступ",
            url=spreadsheet_url,
        )
    )
    keyboard.add(
        Button(
            "✅ Проверить запрос доступа",
            f"{_GOOGLE_CHECK_BUTTON}/{group_id}",
        ).inline()
    )
    keyboard.add(Button("⬅️ Назад", "admins/game_data").inline())
    bot.edit_message_text(
        "<b>Доступ к Google Таблице</b>\n\n"
        "1. Откройте таблицу под нужным Google-аккаунтом.\n"
        "2. Нажмите «Запросить доступ» в Google.\n"
        "3. Вернитесь сюда и нажмите «Проверить запрос доступа».\n\n"
        "Бот разрешит только просмотр.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def _export_group_data(
    bot: TeleBot,
    user_id: int,
    group_id: int,
    google_email: str,
) -> str:
    require_admin_access(bot, user_id, group_id, get_admins_db())
    group = get_access_group_db().get_group(group_id)
    if group is None:
        raise ValueError("Клан не найден")
    database = get_user_data_db()
    return GameDataReport().export(
        group_id,
        group.title,
        google_email,
        database.get_clan_users(group_id),
    )


def _show_game_data_page(context: ClanAdminContext, page: int) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Game data preview requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    _show_preview_waiting(bot, chat_id, message_id)
    try:
        spreadsheet_url = GameDataReport().prepare(
            context.group.group_id,
            context.group.title,
        )
    except Exception as error:
        logger.exception(
            "Unable to prepare game data screen for user_id=%s: %s",
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

    _show_game_data_screen(
        bot,
        chat_id,
        message_id,
        context.group.group_id,
        context.group.title,
        spreadsheet_url,
        page,
    )


def show_game_data(context: ClanAdminContext) -> None:
    _show_game_data_page(context, 0)


def show_game_data_page(context: ClanAdminContext) -> None:
    try:
        page = max(0, int(context.update.data.rsplit("/", maxsplit=1)[-1]))
    except ValueError:
        page = 0
    _show_game_data_page(context, page)


def connect_google_account(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id = callback_query.from_user.id
    try:
        group_id = context.group.group_id
        admins = get_admins_db()
        _request_google_access(
            callback_query, bot, group_id, admins
        )
    except (AdminAccessError, ValueError):
        bot.answer_callback_query(
            callback_query.id,
            "Нет прав администратора выбранного клана.",
            show_alert=True,
        )


def check_google_access_request(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    spreadsheet_url = None
    try:
        group_id = context.group.group_id
        admins = get_admins_db()
        requested_at = admins.get_google_access_requested_at(user_id, group_id)
        if requested_at is None:
            raise ValueError("Сначала откройте таблицу и запросите доступ.")
        report = GameDataReport()
        proposals = report.get_access_proposals(group_id, requested_at)
        if not proposals:
            raise ValueError(
                "Google ещё не передал запрос. Запросите доступ к таблице "
                "и попробуйте снова."
            )
        if len(proposals) > 1:
            raise ValueError(
                "Найдено несколько новых запросов. Попробуйте снова позже."
            )
        proposal = proposals[0]
        previous_email = admins.get_clan_admin_google_email(user_id, group_id)
        if previous_email is not None and previous_email != proposal.email:
            report.revoke_access(group_id, previous_email)
        admins.set_clan_admin_google_email(
            user_id, group_id, proposal.email
        )
        report.approve_access(group_id, proposal.proposal_id)
        spreadsheet_url = report.prepare(group_id, context.group.title)
        _show_export_waiting(bot, chat_id, message_id)
        spreadsheet_url = _export_group_data(
            bot, user_id, group_id, proposal.email
        )
    except (AdminAccessError, ValueError) as error:
        if spreadsheet_url is not None:
            _show_game_data_screen(
                bot,
                chat_id,
                message_id,
                context.group.group_id,
                context.group.title,
                spreadsheet_url,
            )
        bot.answer_callback_query(
            callback_query.id,
            str(error),
            show_alert=True,
        )
        return
    except Exception as error:
        logger.exception(
            "Unable to process Google access request user_id=%s: %s",
            user_id,
            repr(error),
        )
        if spreadsheet_url is not None:
            _show_game_data_screen(
                bot,
                chat_id,
                message_id,
                context.group.group_id,
                context.group.title,
                spreadsheet_url,
            )
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось проверить запрос доступа. Попробуйте ещё раз позже.",
            show_alert=True,
        )
        return

    _show_game_data_screen(
        bot,
        chat_id,
        message_id,
        context.group.group_id,
        context.group.title,
        spreadsheet_url,
    )
    bot.answer_callback_query(
        callback_query.id,
        "Доступ на просмотр выдан. Данные экспортированы.",
    )


def export_game_data(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Google game data export requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    started_at = monotonic()
    result = "failed"
    spreadsheet_url = None
    try:
        page = max(0, int(callback_query.data.rsplit("/", maxsplit=1)[-1]))
    except ValueError:
        page = 0
    try:
        group_id = context.group.group_id
        admins = get_admins_db()
        require_admin_access(bot, user_id, group_id, admins)
        google_email = admins.get_clan_admin_google_email(user_id, group_id)
        if google_email is None:
            result = "access_request_required"
            _request_google_access(
                callback_query, bot, group_id, admins
            )
            return
        spreadsheet_url = GameDataReport().prepare(
            group_id, context.group.title
        )
        _show_export_waiting(bot, chat_id, message_id)
        spreadsheet_url = _export_group_data(
            bot, user_id, group_id, google_email
        )
    except (AdminAccessError, ValueError):
        if spreadsheet_url is not None:
            _show_game_data_screen(
                bot,
                chat_id,
                message_id,
                context.group.group_id,
                context.group.title,
                spreadsheet_url,
                page,
            )
        bot.answer_callback_query(
            callback_query.id,
            "Нет прав администратора выбранного клана.",
            show_alert=True,
        )
        return
    except Exception as error:
        logger.exception(
            "Unable to export game data report for user_id=%s: %s",
            user_id,
            error,
        )
        if spreadsheet_url is not None:
            _show_game_data_screen(
                bot,
                chat_id,
                message_id,
                context.group.group_id,
                context.group.title,
                spreadsheet_url,
                page,
            )
        bot.answer_callback_query(
            callback_query.id,
            "Не удалось экспортировать данные в Google. "
            "Попробуйте ещё раз позже.",
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

    _show_game_data_screen(
        bot,
        chat_id,
        message_id,
        context.group.group_id,
        context.group.title,
        spreadsheet_url,
        page,
    )
    bot.answer_callback_query(
        callback_query.id,
        "Данные экспортированы в Google.",
    )


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.clan_admin_callback(
        show_game_data,
        button="admins/game_data",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        show_game_data_page,
        button=r"admins/game_data/page/[0-9]+",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        connect_google_account,
        button=rf"{_GOOGLE_CONNECT_BUTTON}/-?[0-9]+",
        clan=ClanFromCallback(),
    )
    handlers.clan_admin_callback(
        check_google_access_request,
        button=rf"{_GOOGLE_CHECK_BUTTON}/-?[0-9]+",
        clan=ClanFromCallback(),
    )
    handlers.clan_admin_callback(
        export_game_data,
        button=rf"{_GOOGLE_EXPORT_BUTTON}/-?[0-9]+/[0-9]+",
        clan=ClanFromCallback(segment=-2),
    )
