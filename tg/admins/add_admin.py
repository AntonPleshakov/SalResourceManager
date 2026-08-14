from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from db.admins import Admin
from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.navigation import home
from tg.utils import Button, empty_filter, get_ids, get_user_link, get_username


class AddAdminStates(StatesGroup):
    share_users = State()
    add_admin = State()


CANCEL_ADD_ADMINS_TEXT = "✖️ Отмена"


def add_admins(callback_query: CallbackQuery, bot: TeleBot):
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.info(
        "Add admin requested by user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    request = KeyboardButtonRequestUsers(
        request_id=0, user_is_bot=False, request_username=True
    )
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(
        KeyboardButton(text="👥 Выбрать пользователей", request_users=request)
    )
    keyboard.add(Button(CANCEL_ADD_ADMINS_TEXT, "admins").reply())
    bot.delete_message(chat_id, message_id)
    bot.send_message(
        chat_id,
        formatting.escape_html(
            "Выберите пользователей, которым нужно дать права администратора."
        ),
        reply_markup=keyboard,
    )
    bot.set_state(user_id, AddAdminStates.share_users)


def cancel_add_admins(message: Message, bot: TeleBot):
    user_id, chat_id, _ = get_ids(message)
    logger.info(
        "Admin addition cancelled by user_id=%s username=%s",
        user_id,
        get_username(message),
    )
    bot.delete_state(user_id)
    bot.send_message(
        chat_id,
        "Добавление администраторов отменено.",
        reply_markup=ReplyKeyboardRemove(),
    )
    home(message, bot)


def add_admins_confirmation(message: Message, bot: TeleBot):
    new_admins = [
        Admin(user.username or str(user.user_id), user.user_id)
        for user in message.users_shared.users
    ]
    user_id, chat_id, message_id = get_ids(message)
    logger.info(
        "Admin selection received requester_id=%s username=%s selected=%d",
        user_id,
        get_username(message),
        len(new_admins),
    )
    bot.set_state(user_id, AddAdminStates.add_admin)
    bot.add_data(user_id, new_admins=new_admins)
    bot.send_message(
        chat_id,
        "Пользователи выбраны.",
        reply_markup=ReplyKeyboardRemove(),
    )
    links = [
        get_user_link(admin.user_id.value, admin.username.value)
        for admin in new_admins
    ]
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        Button("✅ Да", "approved").inline(),
        Button("✖️ Нет", "admins").inline(),
    )
    bot.send_message(
        chat_id,
        "Добавить администраторов?\n" + "\n".join(links),
        reply_to_message_id=message_id,
        reply_markup=keyboard,
    )


def add_admins_approved(callback_query: CallbackQuery, bot: TeleBot):
    user_id, _, _ = get_ids(callback_query)
    with bot.retrieve_data(user_id) as data:
        new_admins = data.pop("new_admins")
    logger.info(
        "Admin addition approved requester_id=%s username=%s count=%d",
        user_id,
        get_username(callback_query),
        len(new_admins),
    )
    bot.delete_state(user_id)
    for admin in new_admins:
        get_admins_db().add_admin(admin)
        try:
            bot.send_message(
                admin.user_id.value,
                "Вам выданы права администратора. Отправьте боту сообщение, чтобы открыть меню.",
            )
        except Exception as error:
            logger.warning(
                "Unable to notify new admin user_id=%s username=%s: %s",
                admin.user_id.value,
                admin.username.value,
                error,
            )
    logger.info(
        "Admin addition completed requester_id=%s username=%s count=%d",
        user_id,
        get_username(callback_query),
        len(new_admins),
    )
    bot.answer_callback_query(callback_query.id, "Администраторы добавлены")
    home(callback_query, bot)


def register_handlers(bot: TeleBot):
    logger.debug("Registering add-admin handlers")
    bot.register_callback_query_handler(
        add_admins,
        func=empty_filter,
        button="admins/add_admins",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        cancel_add_admins,
        func=lambda message: message.text in {CANCEL_ADD_ADMINS_TEXT, "Отмена"},
        content_types=["text"],
        chat_types=["private"],
        state=AddAdminStates.share_users,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        add_admins_confirmation,
        content_types=["users_shared"],
        chat_types=["private"],
        state=AddAdminStates.share_users,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        add_admins_approved,
        func=empty_filter,
        button="approved",
        state=AddAdminStates.add_admin,
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
