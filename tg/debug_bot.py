from types import SimpleNamespace

from telebot import TeleBot
from telebot.types import Chat

from db.access_group import AccessGroupDB
from db.admins import AdminsDB
from logger.app_logger import logger


class DebugTeleBot(TeleBot):
    """Use local clan data for Telegram lookups unavailable to a test bot."""

    def __init__(self, token: str, *args, **kwargs):
        super().__init__(token, *args, **kwargs)
        self._debug_access_groups: AccessGroupDB | None = None
        self._debug_admins: AdminsDB | None = None
        self._debug_bot_user_id = int(token.partition(":")[0])

    def configure_fake_clan_data(
        self,
        access_groups: AccessGroupDB,
        admins: AdminsDB,
    ) -> None:
        self._debug_access_groups = access_groups
        self._debug_admins = admins
        logger.info("Debug Telegram clan lookups configured from local database")

    def get_chat(self, chat_id: int, *args, **kwargs):
        if self._debug_access_groups is not None:
            group = self._debug_access_groups.get_group(chat_id)
            if group is not None:
                logger.debug("Using fake Telegram chat chat_id=%s", chat_id)
                return Chat(chat_id, "supergroup", title=group.title)
        return super().get_chat(chat_id, *args, **kwargs)

    def get_chat_member(self, chat_id: int, user_id: int, *args, **kwargs):
        if (
            self._debug_access_groups is None
            or self._debug_access_groups.get_group(chat_id) is None
        ):
            return super().get_chat_member(chat_id, user_id, *args, **kwargs)

        is_administrator = user_id == self._debug_bot_user_id or (
            self._debug_admins is not None
            and self._debug_admins.is_clan_admin(user_id, chat_id)
        )
        status = "administrator" if is_administrator else "member"
        logger.debug(
            "Using fake Telegram membership chat_id=%s user_id=%s status=%s",
            chat_id,
            user_id,
            status,
        )
        return SimpleNamespace(status=status, is_member=True)
