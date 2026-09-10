"""Telegram membership helpers for registered clans."""

from typing import Iterable, List

from telebot import TeleBot
from telebot.types import ChatMember, ChatMemberUpdated

from db.access_group import AccessGroup, AccessGroupDB
from logger.app_logger import logger


class ClanMembershipCheckError(Exception):
    pass


def is_group_member(chat_member: ChatMember) -> bool:
    if chat_member.status == "restricted":
        return bool(chat_member.is_member)
    return chat_member.status in {"creator", "administrator", "member"}


def is_group_admin(chat_member: ChatMember) -> bool:
    return chat_member.status in {"creator", "administrator"}


def get_user_clans(
    bot: TeleBot,
    user_id: int,
    groups: Iterable[AccessGroup],
    *,
    administrators_only: bool = False,
) -> List[AccessGroup]:
    memberships = []
    for group in groups:
        try:
            member = bot.get_chat_member(group.group_id, user_id)
        except Exception as error:
            logger.warning(
                "Unable to check clan membership group_id=%s user_id=%s: %s",
                group.group_id,
                user_id,
                type(error).__name__,
            )
            continue
        allowed = (
            is_group_admin(member)
            if administrators_only
            else is_group_member(member)
        )
        if allowed:
            memberships.append(group)
    return memberships


def refresh_user_accounts(bot: TeleBot, user_id: int, database) -> None:
    """Detach the user's accounts from clans they have left."""
    clan_ids = {
        account.clan_id
        for account in database.get_accounts(user_id)
        if account.clan_id is not None
    }
    for clan_id in clan_ids:
        try:
            member = bot.get_chat_member(clan_id, user_id)
        except Exception as error:
            logger.warning(
                "Unable to refresh account clan membership group_id=%s "
                "user_id=%s: %s",
                clan_id,
                user_id,
                type(error).__name__,
            )
            raise ClanMembershipCheckError(
                "Не удалось проверить участие в клане"
            ) from error
        if not is_group_member(member):
            database.detach_accounts_from_clan(user_id, clan_id)


def refresh_clan_accounts(bot: TeleBot, clan_id: int, database) -> None:
    """Detach accounts whose owners are no longer members of the clan."""
    for user_id in database.get_clan_user_ids(clan_id):
        try:
            member = bot.get_chat_member(clan_id, user_id)
        except Exception as error:
            logger.warning(
                "Unable to refresh clan account membership group_id=%s "
                "user_id=%s: %s",
                clan_id,
                user_id,
                type(error).__name__,
            )
            raise ClanMembershipCheckError(
                "Не удалось проверить состав клана"
            ) from error
        if not is_group_member(member):
            database.detach_accounts_from_clan(user_id, clan_id)


def register_membership_handlers(
    bot: TeleBot,
    groups: AccessGroupDB,
    database,
) -> None:
    """Detach accounts immediately when their owner leaves a clan."""

    def handle_membership_update(update: ChatMemberUpdated) -> None:
        clan_id = int(update.chat.id)
        if groups.get_group(clan_id) is None:
            return
        if not is_group_member(update.old_chat_member):
            return
        if is_group_member(update.new_chat_member):
            return

        user_id = int(update.new_chat_member.user.id)
        detached = database.detach_accounts_from_clan(user_id, clan_id)
        logger.info(
            "Processed clan departure group_id=%s user_id=%s "
            "detached_accounts=%s",
            clan_id,
            user_id,
            detached,
        )

    bot.register_chat_member_handler(handle_membership_update)


def sync_migrated_clan_titles(bot: TeleBot, groups: AccessGroupDB) -> None:
    """Resolve Telegram titles only for clans imported by the migration."""
    for group in groups.get_groups_requiring_title_sync():
        try:
            chat = bot.get_chat(group.group_id)
            title = " ".join(str(chat.title or "").split())
            if not title:
                raise ValueError("Telegram group has no title")
            groups.rename_group(group.group_id, title)
        except Exception as error:
            logger.warning(
                "Unable to initialize migrated clan title group_id=%s: %s",
                group.group_id,
                type(error).__name__,
            )
