from typing import Union

from telebot import TeleBot, util
from telebot.handler_backends import CancelUpdate
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from db.access_group import AccessGroupDB
from db.user_data import UserDataDB
from logger.app_logger import logger
from tg.clans import ClanMembershipCheckError, is_group_member, refresh_user_accounts
from tg.metrics import APPLICATION_METRICS, ApplicationMetrics
from tg.middleware import NoOpPostProcessMiddleware
from tg.utils import get_ids, get_username


ACCESS_DENIED_MESSAGE = (
    "Этот бот помогает участникам кланов в игре Forge Master "
    "учитывать ресурсы, следить за их обновлением и рассчитывать очки войны.\n\n"
    "Доступ предоставляется только участникам зарегистрированных кланов. "
    "Вступите в один из них и снова откройте бот — участие проверится "
    "автоматически. Если вы уже состоите в клане, обратитесь к автору: "
    "@AntonPleshakov."
)
ACCESS_CHECK_FAILED_MESSAGE = (
    "Не удалось проверить ваше участие в зарегистрированных кланах: Telegram временно "
    "не ответил. Попробуйте снова через несколько минут. Если проблема "
    "повторяется, обратитесь к автору: @AntonPleshakov."
)
ACCESS_GROUP_NOT_REGISTERED_MESSAGE = (
    "В боте ещё не зарегистрировано ни одного клана. Обратитесь к автору: "
    "@AntonPleshakov."
)
ACCESS_DENIED_ALERT_MESSAGE = "Доступ сейчас закрыт."


def is_group_registration_command(
    update: Union[Message, CallbackQuery],
) -> bool:
    return (
        isinstance(update, Message)
        and update.chat.type in {"group", "supergroup"}
        and (util.extract_command(update.text or "") or "").casefold()
        == "register_group"
    )


def _get_chat_type(update: Union[Message, CallbackQuery]) -> str | None:
    if isinstance(update, CallbackQuery):
        return None if update.message is None else update.message.chat.type
    return update.chat.type


class GroupAccessMiddleware(NoOpPostProcessMiddleware):
    def __init__(
        self,
        bot: TeleBot,
        access_group_db: AccessGroupDB,
        metrics: ApplicationMetrics = APPLICATION_METRICS,
        user_data_db: UserDataDB | None = None,
    ):
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._bot = bot
        self._access_group_db = access_group_db
        self._user_data_db = user_data_db
        self._metrics = metrics

    def _group_link_keyboard(self, groups) -> InlineKeyboardMarkup | None:
        keyboard = InlineKeyboardMarkup(row_width=1)
        for registered_group in groups:
            try:
                group = self._bot.get_chat(registered_group.group_id)
            except Exception as error:
                logger.warning(
                    "Unable to get clan link group_id=%s: %s",
                    registered_group.group_id,
                    type(error).__name__,
                )
                continue
            invite_link = group.invite_link
            username = str(group.username or "").lstrip("@")
            group_url = invite_link or (
                f"https://t.me/{username}" if username else None
            )
            if group_url:
                keyboard.add(
                    InlineKeyboardButton(
                        f"👥 {registered_group.title}", url=group_url
                    )
                )
        return keyboard if keyboard.keyboard else None

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
        self, update: Union[Message, CallbackQuery], _: dict
    ) -> CancelUpdate | None:
        if _get_chat_type(update) != "private":
            if is_group_registration_command(update):
                logger.debug("Allowing access group registration command")
                self._metrics.access_checks.labels(result="bypassed").inc()
                return None
            logger.debug("Ignoring non-private Telegram update")
            self._metrics.access_checks.labels(result="ignored").inc()
            return CancelUpdate()

        groups = self._access_group_db.get_groups()
        if not groups:
            user_id = get_ids(update)[0]
            logger.info(
                "Group access denied for user_id=%s username=%s: "
                "group is not configured",
                user_id,
                get_username(update),
            )
            self._deny_access(update, ACCESS_GROUP_NOT_REGISTERED_MESSAGE)
            self._metrics.access_checks.labels(result="unconfigured").inc()
            return CancelUpdate()

        user_id = get_ids(update)[0]
        errors = []
        if self._user_data_db is not None:
            try:
                refresh_user_accounts(self._bot, user_id, self._user_data_db)
            except ClanMembershipCheckError:
                self._deny_access(update, ACCESS_CHECK_FAILED_MESSAGE)
                self._metrics.access_checks.labels(result="error").inc()
                return CancelUpdate()
            attached_clan_ids = {
                account.clan_id
                for account in self._user_data_db.get_accounts(user_id)
                if account.clan_id is not None
            }
            if attached_clan_ids:
                self._metrics.access_checks.labels(result="allowed").inc()
                return None

        for group in groups:
            try:
                member = self._bot.get_chat_member(group.group_id, user_id)
            except Exception as error:
                errors.append(error)
                logger.warning(
                    "Unable to check clan membership group_id=%s user_id=%s "
                    "username=%s: %s",
                    group.group_id,
                    user_id,
                    get_username(update),
                    error,
                )
                continue
            if is_group_member(member):
                self._metrics.access_checks.labels(result="allowed").inc()
                return None

        if errors:
            self._deny_access(update, ACCESS_CHECK_FAILED_MESSAGE)
            self._metrics.access_checks.labels(result="error").inc()
            return CancelUpdate()

        logger.info(
            "Group access denied for user_id=%s username=%s: not a member",
            user_id,
            get_username(update),
        )
        self._deny_access(
            update,
            ACCESS_DENIED_MESSAGE,
            self._group_link_keyboard(groups),
        )
        self._metrics.access_checks.labels(result="denied").inc()
        return CancelUpdate()
