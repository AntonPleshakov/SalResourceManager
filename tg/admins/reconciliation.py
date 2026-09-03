"""Periodic reconciliation of clan administrator access."""

from dataclasses import dataclass

from telebot import TeleBot

from db.access_group import AccessGroupDB
from db.admins import AdminsDB
from db.initializer import get_access_group_db, get_admins_db
from logger.app_logger import logger
from reports.game_data import GameDataReport
from tg.admins.common import remove_clan_admin_access
from tg.clans import is_group_member


@dataclass(frozen=True)
class AdminReconciliationResult:
    current: int = 0
    revoked: int = 0
    check_failed: int = 0
    revoke_failed: int = 0


def reconcile_clan_admins(
    bot: TeleBot,
    groups: AccessGroupDB | None = None,
    admins: AdminsDB | None = None,
    report: GameDataReport | None = None,
) -> AdminReconciliationResult:
    group_database = groups or get_access_group_db()
    admin_database = admins or get_admins_db()
    game_data_report = report or GameDataReport()
    current = 0
    revoked = 0
    check_failed = 0
    revoke_failed = 0

    for group in group_database.get_groups():
        for admin in admin_database.get_clan_admins(group.group_id):
            user_id = int(admin.user_id.value)
            try:
                member = bot.get_chat_member(group.group_id, user_id)
            except Exception as error:
                check_failed += 1
                logger.warning(
                    "Unable to reconcile clan admin membership "
                    "user_id=%s group_id=%s: %s",
                    user_id,
                    group.group_id,
                    type(error).__name__,
                )
                continue
            if is_group_member(member):
                current += 1
                continue
            try:
                remove_clan_admin_access(
                    user_id,
                    group.group_id,
                    admin_database,
                    game_data_report,
                )
            except Exception as error:
                revoke_failed += 1
                logger.warning(
                    "Unable to revoke stale clan admin access "
                    "user_id=%s group_id=%s: %s",
                    user_id,
                    group.group_id,
                    type(error).__name__,
                )
                continue
            revoked += 1

    result = AdminReconciliationResult(
        current=current,
        revoked=revoked,
        check_failed=check_failed,
        revoke_failed=revoke_failed,
    )
    logger.info(
        "Clan admin reconciliation completed current=%d revoked=%d "
        "check_failed=%d revoke_failed=%d",
        result.current,
        result.revoked,
        result.check_failed,
        result.revoke_failed,
    )
    return result
