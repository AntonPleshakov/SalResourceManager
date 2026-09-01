from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup
from telebot.types import (
    CallbackQuery,
    KeyboardButton,
    KeyboardButtonRequestChat,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from db.initializer import get_access_group_db, get_admins_db
from db.admins import Admin
from logger.app_logger import logger
from tg.clans import is_group_admin
from tg.utils import empty_filter, get_ids, get_username


GROUP_REGISTRATION_REQUEST_ID = 1


class GroupRegistrationStates(StatesGroup):
    select_group = State()


NOT_ADMIN_MESSAGE = "Только администратор бота может зарегистрировать группу."
GROUP_SELECTION_MESSAGE = (
    "Выберите группу клана, в которую уже добавлен бот. "
    "Бот должен быть администратором этой группы."
)
USER_NOT_GROUP_ADMIN_MESSAGE = (
    "Регистрация отклонена: вы должны быть администратором этой группы."
)
BOT_NOT_ADMIN_MESSAGE = (
    "Регистрация отклонена: бот должен быть администратором этой группы."
)
INVALID_GROUP_MESSAGE = "Можно зарегистрировать только группу или супергруппу."
INVALID_GROUP_SELECTION_MESSAGE = (
    "Эта группа была выбрана не через форму регистрации. "
    "Запустите регистрацию заново."
)
REGISTRATION_FAILED_MESSAGE = (
    "Не удалось проверить или зарегистрировать группу. Попробуйте ещё раз позже."
)
REGISTRATION_SUCCESS_MESSAGE = "Группа «{title}» зарегистрирована."


def _group_selection_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
        row_width=1,
        input_field_placeholder="Выберите группу клана",
    )
    keyboard.add(
        KeyboardButton(
            "🏰 Выбрать группу",
            request_chat=KeyboardButtonRequestChat(
                request_id=GROUP_REGISTRATION_REQUEST_ID,
                chat_is_channel=False,
                bot_is_member=True,
                request_title=True,
                request_username=True,
            ),
        )
    )
    return keyboard


def request_group_registration(update: CallbackQuery, bot: TeleBot) -> None:
    user_id, chat_id = get_ids(update)[:2]
    logger.info(
        "Access group selection requested by user_id=%s username=%s",
        user_id,
        get_username(update),
    )
    if not get_admins_db().is_admin(user_id):
        logger.warning(
            "Access group selection rejected for non-admin user_id=%s username=%s",
            user_id,
            get_username(update),
        )
        bot.send_message(chat_id, NOT_ADMIN_MESSAGE)
        return

    bot.send_message(
        chat_id,
        GROUP_SELECTION_MESSAGE,
        reply_markup=_group_selection_keyboard(),
    )
    bot.set_state(user_id, GroupRegistrationStates.select_group)


def _register_group(
    message: Message,
    bot: TeleBot,
    group_id: int,
    *,
    check_user_admin: bool,
) -> None:
    user_id = message.from_user.id
    remove_keyboard = message.chat.type == "private"
    reply_markup = ReplyKeyboardRemove() if remove_keyboard else None
    try:
        group = bot.get_chat(group_id)
        if group.type not in {"group", "supergroup"}:
            logger.warning(
                "Access group registration rejected for chat_id=%s type=%s",
                group_id,
                group.type,
            )
            bot.reply_to(
                message,
                INVALID_GROUP_MESSAGE,
                reply_markup=reply_markup,
            )
            return

        if check_user_admin:
            user_member = bot.get_chat_member(group_id, user_id)
            if not is_group_admin(user_member):
                logger.warning(
                    "Access group registration rejected: user_id=%s is not an "
                    "admin in chat_id=%s",
                    user_id,
                    group_id,
                )
                bot.reply_to(
                    message,
                    USER_NOT_GROUP_ADMIN_MESSAGE,
                    reply_markup=reply_markup,
                )
                return

        bot_member = bot.get_chat_member(group_id, bot.get_me().id)
        if not is_group_admin(bot_member):
            logger.warning(
                "Access group registration rejected: bot is not admin in chat_id=%s",
                group_id,
            )
            bot.reply_to(
                message,
                BOT_NOT_ADMIN_MESSAGE,
                reply_markup=reply_markup,
            )
            return

        title = str(group.title or group_id)
        get_access_group_db().add_group(group_id, title)
        admins = get_admins_db()
        admins.add_admin(Admin(get_username(message), user_id), group_id)
        admins.select_group(user_id, group_id)
    except Exception as error:
        logger.exception("Unable to register access group: %s", error)
        bot.reply_to(
            message,
            REGISTRATION_FAILED_MESSAGE,
            reply_markup=reply_markup,
        )
        return

    title = formatting.escape_html(title)
    logger.info(
        "Access group chat_id=%s registered by user_id=%s username=%s",
        group_id,
        user_id,
        get_username(message),
    )
    bot.reply_to(
        message,
        REGISTRATION_SUCCESS_MESSAGE.format(title=title),
        reply_markup=reply_markup,
    )


def register_selected_group(message: Message, bot: TeleBot) -> None:
    """Register a group selected by an existing bot administrator."""
    user_id = message.from_user.id
    bot.delete_state(user_id)
    shared_chat = message.chat_shared
    logger.info(
        "Access group registration requested by user_id=%s username=%s "
        "chat_id=%s request_id=%s",
        user_id,
        get_username(message),
        shared_chat.chat_id,
        shared_chat.request_id,
    )

    if not get_admins_db().is_admin(user_id):
        logger.warning(
            "Access group registration rejected for non-admin user_id=%s username=%s",
            user_id,
            get_username(message),
        )
        bot.reply_to(message, NOT_ADMIN_MESSAGE, reply_markup=ReplyKeyboardRemove())
        return

    if shared_chat.request_id != GROUP_REGISTRATION_REQUEST_ID:
        logger.warning(
            "Access group registration rejected for unexpected request_id=%s",
            shared_chat.request_id,
        )
        bot.reply_to(
            message,
            INVALID_GROUP_SELECTION_MESSAGE,
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    _register_group(message, bot, shared_chat.chat_id, check_user_admin=False)


def register_current_group(message: Message, bot: TeleBot) -> None:
    """Register the Telegram group in which the command was sent."""
    _register_group(message, bot, message.chat.id, check_user_admin=True)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering access group handlers")
    bot.register_message_handler(
        register_current_group,
        commands=["register_group"],
        chat_types=["group", "supergroup"],
        pass_bot=True,
    )
    bot.register_callback_query_handler(
        request_group_registration,
        func=empty_filter,
        button="admins/register_group",
        is_private=True,
        is_admin=True,
        pass_bot=True,
    )
    bot.register_message_handler(
        register_selected_group,
        content_types=["chat_shared"],
        chat_types=["private"],
        state=GroupRegistrationStates.select_group,
        pass_bot=True,
    )
