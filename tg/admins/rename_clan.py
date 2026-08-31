from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from db.initializer import get_access_group_db, get_admins_db
from logger.app_logger import logger
from tg.admins.common import get_active_admin_group
from tg.utils import Button, empty_filter, get_ids, get_username


MAX_CLAN_TITLE_LENGTH = 100


class RenameClanStates(StatesGroup):
    title = State()


def request_clan_rename(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    group = get_active_admin_group(user_id)
    bot.set_state(user_id, RenameClanStates.title)
    bot.add_data(user_id, rename_clan_group_id=group.group_id)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("⬅️ Отмена", "admins").inline())
    bot.edit_message_text(
        "<b>Переименование клана</b>\n\n"
        f"Текущее название: <b>{formatting.escape_html(group.title)}</b>.\n"
        "Отправьте новое название.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def rename_clan(message: Message, bot: TeleBot) -> None:
    user_id, chat_id, _ = get_ids(message)
    with bot.retrieve_data(user_id) as data:
        group_id = data.get("rename_clan_group_id")

    if not isinstance(group_id, int) or not get_admins_db().is_admin(
        user_id, group_id
    ):
        bot.delete_state(user_id)
        bot.send_message(
            chat_id,
            "Нет прав на переименование этого клана.",
            reply_markup=_back_keyboard(),
        )
        return

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


def _back_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("⬅️ Назад в админ-панель", "admins").inline())
    return keyboard


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering rename-clan handlers")
    bot.register_callback_query_handler(
        request_clan_rename,
        func=empty_filter,
        button="admins/rename_clan",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        rename_clan,
        content_types=["text"],
        chat_types=["private"],
        state=RenameClanStates.title,
        is_admin=True,
        pass_bot=True,
    )
