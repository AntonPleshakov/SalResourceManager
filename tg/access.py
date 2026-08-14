import re
from typing import Union

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import (
    CallbackQuery,
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from db.access_group import AccessGroupDB
from logger.app_logger import logger
from tg.utils import get_ids, get_username


ACCESS_DENIED_MESSAGE = (
    "Этот бот помогает участникам клана ShadowAl в игре Forge Master "
    "учитывать ресурсы, следить за их обновлением и рассчитывать очки войны.\n\n"
    "Доступ к боту предоставляется только участникам клана. Вступите в "
    "ShadowAl и снова откройте бот — участие проверится автоматически. Если "
    "вы уже состоите в клане или вам нужно приглашение, обратитесь к автору: "
    "@AntonPleshakov."
)
ACCESS_CHECK_FAILED_MESSAGE = (
    "Не удалось проверить ваше участие в клане ShadowAl: Telegram временно "
    "не ответил. Попробуйте снова через несколько минут. Если проблема "
    "повторяется, обратитесь к автору: @AntonPleshakov."
)
ACCESS_GROUP_NOT_REGISTERED_MESSAGE = (
    "Бот ещё не настроен для работы с кланом ShadowAl. Обратитесь к автору: "
    "@AntonPleshakov."
)
ACCESS_DENIED_ALERT_MESSAGE = "Доступ сейчас закрыт. Я отправил подробности в чат."
REGISTER_GROUP_COMMAND_PATTERN = re.compile(
    r"^/register_group(?:@[A-Za-z0-9_]+)?(?:\s|$)", re.IGNORECASE
)


def is_group_member(chat_member: ChatMember) -> bool:
    if chat_member.status == "restricted":
        return bool(getattr(chat_member, "is_member", False))
    return chat_member.status in {"creator", "administrator", "member"}


def is_group_registration_message(update: Union[Message, CallbackQuery]) -> bool:
    return (
        isinstance(update, Message)
        and update.chat.type in {"group", "supergroup"}
        and REGISTER_GROUP_COMMAND_PATTERN.match(update.text or "") is not None
    )


class GroupAccessMiddleware(BaseMiddleware):
    def __init__(self, bot: TeleBot, access_group_db: AccessGroupDB):
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._bot = bot
        self._access_group_db = access_group_db

    def _group_link_keyboard(
        self, group_id: int
    ) -> InlineKeyboardMarkup | None:
        try:
            group = self._bot.get_chat(group_id)
        except Exception as error:
            logger.warning(
                "Unable to get access group link group_id=%s: %s",
                group_id,
                type(error).__name__,
            )
            return None

        invite_link = getattr(group, "invite_link", None)
        username = str(getattr(group, "username", "") or "").lstrip("@")
        group_url = invite_link or (f"https://t.me/{username}" if username else None)
        if not group_url:
            return None

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(InlineKeyboardButton("👥 Открыть группу", url=group_url))
        return keyboard

    def _deny_access(
        self,
        update: Union[Message, CallbackQuery],
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        try:
            if isinstance(update, CallbackQuery):
                self._bot.answer_callback_query(
                    update.id,
                    text=ACCESS_DENIED_ALERT_MESSAGE,
                    show_alert=True,
                )
                self._bot.send_message(
                    update.message.chat.id,
                    text,
                    reply_markup=reply_markup,
                )
            elif reply_markup is not None:
                self._bot.reply_to(update, text, reply_markup=reply_markup)
            else:
                self._bot.reply_to(update, text)
        except Exception as error:
            logger.warning(
                "Unable to send group access denial: %s", type(error).__name__
            )

    def pre_process(
        self, update: Union[Message, CallbackQuery], data: dict
    ) -> CancelUpdate | None:
        if is_group_registration_message(update):
            logger.debug("Allowing access group registration command")
            return None

        group_id = self._access_group_db.get_group_id()
        if group_id is None:
            user_id, _, _ = get_ids(update)
            logger.info(
                "Group access denied for user_id=%s username=%s: "
                "group is not configured",
                user_id,
                get_username(update),
            )
            self._deny_access(update, ACCESS_GROUP_NOT_REGISTERED_MESSAGE)
            return CancelUpdate()

        user_id, _, _ = get_ids(update)
        try:
            member = self._bot.get_chat_member(group_id, user_id)
        except Exception as error:
            logger.warning(
                "Unable to check group membership for user_id=%s username=%s: %s",
                user_id,
                get_username(update),
                error,
            )
            self._deny_access(update, ACCESS_CHECK_FAILED_MESSAGE)
            return CancelUpdate()

        if is_group_member(member):
            return None

        logger.info(
            "Group access denied for user_id=%s username=%s: not a member",
            user_id,
            get_username(update),
        )
        self._deny_access(
            update,
            ACCESS_DENIED_MESSAGE,
            self._group_link_keyboard(group_id),
        )
        return CancelUpdate()

    def post_process(
        self,
        update: Union[Message, CallbackQuery],
        data: dict,
        exception: BaseException | None,
    ) -> None:
        pass
