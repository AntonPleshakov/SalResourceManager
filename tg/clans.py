"""Telegram membership helpers for registered clans."""

from typing import Iterable, List

from telebot import TeleBot
from telebot.types import ChatMember

from db.access_group import AccessGroup, AccessGroupDB
from logger.app_logger import logger


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
