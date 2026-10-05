from datetime import date
from decimal import Decimal
from typing import Iterable, List, Literal

from telebot import TeleBot, formatting
from common.datetime_utils import format_last_update
from db.initializer import get_access_group_db, get_user_data_db
from logger.app_logger import logger
from resources.user_data import UserData
from resources.war import WAR_STAGES, WarPointsCalculator
from tg.handlers import ActiveClan, ClanAdminContext, HandlerRegistry
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    confirmation_buttons,
    edit_rich_message,
    heading,
    highlight_metric,
    input_rich_message,
)
from tg.war.personal import _personal_war_points_text
from tg.utils import (
    format_points,
    format_user_identity,
    get_ids,
    get_username,
)


MAX_RICH_MESSAGE_LENGTH = 30_000
PlayerSort = Literal["updates", "points"]


def _format_last_update(updated_on: date | None) -> str:
    return format_last_update(updated_on)


def _user_link(user: UserData) -> str:
    identity = format_user_identity(
        user.username.value or str(user.user_id.value), user.tag.value
    )
    return (
        f'<a href="tg://user?id={user.user_id.value}">'
        f"{formatting.escape_html(identity)}</a>"
    )


def build_last_updates_report(
    users: Iterable[UserData],
) -> str:
    sorted_users = sorted(
        users,
        key=lambda user: user.get_last_resource_updated_on() or date.min,
        reverse=True,
    )
    user_blocks = [
        f"<p>{_user_link(user)}<br>"
        f"<i>{_format_last_update(user.get_last_resource_updated_on())}</i></p>"
        for user in sorted_users
    ]
    header = "".join(
        (
            heading("Последнее обновление ресурсов"),
            highlight_metric("Всего аккаунтов", str(len(sorted_users))),
        )
    )
    if not user_blocks:
        return f"{header}<p>Аккаунтов пока нет.</p>"
    return f"{header}\n\n" + "\n\n".join(user_blocks)


def _war_points(user: UserData, calculator: WarPointsCalculator) -> Decimal:
    return calculator.calculate([user], WAR_STAGES).total


def build_players_report(
    users: Iterable[UserData],
    calculator: WarPointsCalculator,
    *,
    sort: PlayerSort = "updates",
) -> str:
    users_with_points = [(user, _war_points(user, calculator)) for user in users]
    if sort == "points":
        users_with_points.sort(
            key=lambda item: (
                item[1],
                item[0].get_last_resource_updated_on() or date.min,
            ),
            reverse=True,
        )
    else:
        users_with_points.sort(
            key=lambda item: (
                item[0].get_last_resource_updated_on() or date.min,
                item[1],
            ),
            reverse=True,
        )

    user_blocks = []
    for user, points in users_with_points:
        account_id = user.account_id.value
        user_blocks.append(
            "".join(
                (
                    f"<p>{_user_link(user)}<br>",
                    "<i>"
                    f"{_format_last_update(user.get_last_resource_updated_on())}"
                    "</i><br>",
                    f"<b>Очки войны: {format_points(points)}</b></p>",
                    button_row(
                        (
                            callback_button(
                                "⚔️ Посмотреть очки войны",
                                f"admins/players/war/{account_id}/{sort}",
                            ),
                            callback_button(
                                "🚫 Убрать из клана",
                                f"admins/players/remove/{account_id}/{sort}",
                                style="danger",
                            ),
                        )
                    ),
                )
            )
        )

    header = "".join(
        (
            heading("Игроки клана"),
            highlight_metric("Всего аккаунтов", str(len(users_with_points))),
        )
    )
    if not user_blocks:
        return f"{header}<p>Аккаунтов пока нет.</p>"
    return f"{header}\n\n" + "\n\n".join(user_blocks)


def _split_report(report: str) -> List[str]:
    if len(report) <= MAX_RICH_MESSAGE_LENGTH:
        return [report]

    chunks: List[str] = []
    current = ""
    for block in report.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= MAX_RICH_MESSAGE_LENGTH:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block
    if current:
        chunks.append(current)
    return chunks


def _parse_account_action(callback_data: str) -> tuple[int, PlayerSort]:
    parts = callback_data.split("/")
    try:
        account_id = int(parts[-2])
    except (IndexError, ValueError) as error:
        raise ValueError("Игровой аккаунт не найден") from error
    sort: PlayerSort = "points" if parts[-1] == "points" else "updates"
    return account_id, sort


def _find_clan_account(
    context: ClanAdminContext, account_id: int
) -> UserData | None:
    return next(
        (
            user
            for user in get_user_data_db().get_clan_users(context.group.group_id)
            if user.account_id.value == account_id
        ),
        None,
    )


def _show_players(context: ClanAdminContext, sort: PlayerSort) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    database = get_user_data_db()
    users = database.get_clan_users(context.group.group_id)
    technologies = get_access_group_db().get_clan_technologies(
        context.group.group_id
    )
    report = build_players_report(
        users,
        WarPointsCalculator(technologies),
        sort=sort,
    )
    chunks = _split_report(report)
    sort_button = button_row(
        (
            callback_button(
                (
                    "🕒 Сортировать по обновлению"
                    if sort == "points"
                    else "⬇️ Сортировать по очкам войны"
                ),
                (
                    "admins/players"
                    if sort == "points"
                    else "admins/players/points"
                ),
                style="primary",
            ),
        )
    )
    navigation = "".join(
        (sort_button, back_button("⬅️ Админ-панель", "admins"))
    )

    logger.info(
        "Clan players requested by user_id=%s username=%s users=%d sort=%s",
        user_id,
        get_username(callback_query),
        len(users),
        sort,
    )
    first_message = input_rich_message(
        (chunks[0], navigation if len(chunks) == 1 else "")
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        first_message,
    )
    for index, chunk in enumerate(chunks[1:], start=1):
        bot.send_rich_message(
            chat_id,
            input_rich_message(
                (chunk, navigation if index == len(chunks) - 1 else "")
            ),
        )


def players(context: ClanAdminContext) -> None:
    _show_players(context, "updates")


def players_by_points(context: ClanAdminContext) -> None:
    _show_players(context, "points")


def player_war_points(context: ClanAdminContext) -> None:
    callback_query = context.update
    account_id, sort = _parse_account_action(callback_query.data)
    user = _find_clan_account(context, account_id)
    if user is None:
        context.bot.answer_callback_query(
            callback_query.id,
            "Игровой аккаунт не найден в выбранном клане",
            show_alert=True,
        )
        return
    technologies = get_access_group_db().get_clan_technologies(
        context.group.group_id
    )
    edit_rich_message(
        context.bot,
        context.chat_id,
        context.message_id,
        input_rich_message(
            (
                _personal_war_points_text(user, technologies),
                back_button(
                    "⬅️ Игроки клана",
                    "admins/players/points"
                    if sort == "points"
                    else "admins/players",
                ),
            )
        ),
    )


def confirm_remove_player(context: ClanAdminContext) -> None:
    callback_query = context.update
    account_id, sort = _parse_account_action(callback_query.data)
    user = _find_clan_account(context, account_id)
    if user is None:
        context.bot.answer_callback_query(
            callback_query.id,
            "Игровой аккаунт не найден в выбранном клане",
            show_alert=True,
        )
        return
    identity = formatting.escape_html(
        format_user_identity(
            user.username.value or str(user.user_id.value), user.tag.value
        )
    )
    edit_rich_message(
        context.bot,
        context.chat_id,
        context.message_id,
        input_rich_message(
            (
                heading("Убрать аккаунт из клана?"),
                f"<p>{identity}</p>",
                "<p>Данные аккаунта сохранятся, но он больше не будет "
                "учитываться в списках и расчётах клана.</p>",
                confirmation_buttons(
                    "Убрать из клана",
                    f"admins/players/remove/confirm/{account_id}/{sort}",
                    "⬅️ Игроки клана",
                    "admins/players/points"
                    if sort == "points"
                    else "admins/players",
                    destructive=True,
                ),
            )
        ),
    )


def remove_player(context: ClanAdminContext) -> None:
    callback_query = context.update
    account_id, sort = _parse_account_action(callback_query.data)
    user = _find_clan_account(context, account_id)
    if user is None:
        context.bot.answer_callback_query(
            callback_query.id,
            "Игровой аккаунт не найден в выбранном клане",
            show_alert=True,
        )
        return
    get_user_data_db().detach_account_from_clan(
        user.user_id.value,
        account_id,
    )
    context.bot.answer_callback_query(
        callback_query.id,
        "Игровой аккаунт убран из клана",
    )
    logger.info(
        "Clan account detached by admin user_id=%s account_id=%s clan_id=%s",
        context.user_id,
        account_id,
        context.group.group_id,
    )
    _show_players(context, sort)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering clan players handlers")
    handlers = HandlerRegistry(bot)
    handlers.clan_admin_callback(
        players,
        button="admins/players",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        players_by_points,
        button="admins/players/points",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        player_war_points,
        button=r"admins/players/war/[0-9]+/(updates|points)",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        confirm_remove_player,
        button=r"admins/players/remove/[0-9]+/(updates|points)",
        clan=ActiveClan(),
    )
    handlers.clan_admin_callback(
        remove_player,
        button=r"admins/players/remove/confirm/[0-9]+/(updates|points)",
        clan=ActiveClan(),
    )
