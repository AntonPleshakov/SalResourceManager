from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import InlineKeyboardMarkup

from db.initializer import get_access_group_db
from logger.app_logger import logger
from tg.handlers import (
    ActiveClan,
    ClanAdminContext,
    ClanFromState,
    HandlerRegistry,
)
from tg.utils import Button, get_ids, get_username


MAX_CLAN_TITLE_LENGTH = 100


class RenameClanStates(StatesGroup):
    title = State()


def _back_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    return keyboard


def request_clan_rename(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    bot.set_state(user_id, RenameClanStates.title)
    bot.add_data(user_id, rename_clan_group_id=context.group.group_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("⬅️ Отмена", "admins").inline())
    bot.edit_message_text(
        "<b>Переименование клана</b>\n\n"
        "Текущее название: "
        f"<b>{formatting.escape_html(context.group.title)}</b>.\n"
        "Отправьте новое название.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def rename_clan(context: ClanAdminContext) -> None:
    message = context.update
    bot = context.bot
    user_id, chat_id = get_ids(message)[:2]
    group_id = context.group.group_id

    title = " ".join((message.text or "").split())
    if not title:
        bot.send_message(chat_id, "Название клана не может быть пустым.")
        return
    if len(title) > MAX_CLAN_TITLE_LENGTH:
        bot.send_message(
            chat_id,
            f"Название клана не должно быть длиннее "
            f"{MAX_CLAN_TITLE_LENGTH} символов.",
        )
        return

    group = get_access_group_db().rename_group(group_id, title)
    bot.delete_state(user_id)
    logger.info(
        "Clan renamed by admin user_id=%s username=%s group_id=%s",
        user_id,
        get_username(message),
        group_id,
    )
    bot.send_message(
        chat_id,
        f"Клан переименован: <b>"
        f"{formatting.escape_html(group.title)}</b>.",
        reply_markup=_back_keyboard(),
    )


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering rename-clan handlers")
    handlers = HandlerRegistry(bot)
    handlers.clan_admin_callback(
        request_clan_rename,
        button="admins/rename_clan",
        clan=ActiveClan(),
    )
    handlers.clan_admin_message(
        rename_clan,
        content_types=["text"],
        state=RenameClanStates.title,
        clan=ClanFromState("rename_clan_group_id"),
    )
