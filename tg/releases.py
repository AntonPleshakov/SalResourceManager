from typing import Sequence, Union

from html import escape

from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from common.datetime_utils import format_last_update
from db.initializer import get_release_views_db
from logger.app_logger import logger
from resources.releases import CURRENT_VERSION, RELEASES, Release, unseen_releases
from tg.handlers import HandlerRegistry
from tg.rich import (
    button_row,
    callback_button,
    deliver_rich_message,
    details,
    footer,
    heading,
    input_rich_message,
)
from tg.utils import get_ids, get_username


def format_release_notes(releases: Sequence[Release]) -> str:
    sections = [heading("🆕 Что нового")]
    for index, release in enumerate(reversed(releases)):
        changes = "".join(
            f"<li>{escape(change)}</li>" for change in release.changes
        )
        released_on = format_last_update(release.released_on)
        if index == 0:
            sections.extend(
                (
                    heading(f"Версия {release.version}", level=3),
                    footer(released_on),
                    f"<ul>{changes}</ul>",
                )
            )
            continue
        sections.append(
            details(
                f"Версия {release.version} · {released_on}",
                f"<ul>{changes}</ul>",
            )
        )
    return "".join(sections)


def _show_notes(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    releases: Sequence[Release],
) -> None:
    user_id = get_ids(message)[0]
    deliver_rich_message(
        message,
        bot,
        input_rich_message(
            (
                format_release_notes(releases),
                button_row(
                    (
                        callback_button(
                            "🏠 Перейти в меню", "home", style="primary"
                        ),
                    )
                ),
            )
        ),
    )
    get_release_views_db().mark_seen(
        user_id,
        get_username(message),
        CURRENT_VERSION,
    )


def mark_current_release_seen(
    message: Union[Message, CallbackQuery],
) -> None:
    user_id = get_ids(message)[0]
    try:
        get_release_views_db().mark_seen(
            user_id,
            get_username(message),
            CURRENT_VERSION,
        )
    except RuntimeError:
        logger.warning("Release views storage is unavailable while marking release")


def show_unseen_releases(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    user_id = get_ids(message)[0]
    username = get_username(message)
    try:
        release_views = get_release_views_db()
    except RuntimeError:
        logger.warning("Release views storage is unavailable while opening home menu")
        return False

    releases = unseen_releases(release_views.get_last_seen_version(user_id))
    if not releases:
        release_views.update_username(user_id, username)
        return False

    logger.info(
        "Showing unseen releases to user_id=%s username=%s versions=%s",
        user_id,
        username,
        [release.version for release in releases],
    )
    _show_notes(message, bot, releases)
    return True


def show_release_notes(callback_query: CallbackQuery, bot: TeleBot) -> None:
    logger.debug(
        "Showing current release to user_id=%s username=%s",
        callback_query.from_user.id,
        get_username(callback_query),
    )
    _show_notes(callback_query, bot, RELEASES[-1:])


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering release notes handlers")
    HandlerRegistry(bot).private_callback(
        show_release_notes,
        button="releases",
    )
