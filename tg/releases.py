from typing import Sequence, Union

from telebot import TeleBot, formatting
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.release_views import get_release_views_db
from logger.app_logger import logger
from resources.releases import CURRENT_VERSION, RELEASES, Release, unseen_releases
from tg.utils import Button, empty_filter, get_ids, get_username


def format_release_notes(releases: Sequence[Release]) -> str:
    sections = []
    for release in reversed(releases):
        changes = "\n".join(
            f"• {formatting.escape_html(change)}" for change in release.changes
        )
        sections.append(
            f"<b>Версия {release.version}</b> · {release.released_on:%d.%m.%Y}\n"
            f"{changes}"
        )
    return "🆕 <b>Что нового</b>\n\n" + "\n\n".join(sections)


def _show_notes(
    message: Union[Message, CallbackQuery],
    bot: TeleBot,
    releases: Sequence[Release],
) -> None:
    user_id, chat_id, message_id = get_ids(message)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Перейти в меню", "home").inline())
    text = format_release_notes(releases)
    if isinstance(message, CallbackQuery):
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)
    get_release_views_db().mark_seen(
        user_id,
        get_username(message),
        CURRENT_VERSION,
    )


def show_unseen_releases(
    message: Union[Message, CallbackQuery], bot: TeleBot
) -> bool:
    user_id, _, _ = get_ids(message)
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
    bot.register_callback_query_handler(
        show_release_notes,
        func=empty_filter,
        button="releases",
        is_private=True,
        pass_bot=True,
    )
