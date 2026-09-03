from datetime import datetime, timedelta, timezone

import pytest

from db.access_group import AccessGroupDB
from db.admins import Admin, AdminsDB
from db.database import Database
from tg.admins.reconciliation import reconcile_clan_admins
from tg.scheduling.admin_reconciliation import next_admin_reconciliation


MOSCOW_TIMEZONE = timezone(timedelta(hours=3))


class MembershipBot:
    def __init__(self, statuses):
        self._statuses = statuses

    def get_chat_member(self, group_id, user_id):
        status = self._statuses[(group_id, user_id)]
        if isinstance(status, Exception):
            raise status
        return type("Member", (), {"status": status})()


class RecordingReport:
    def __init__(self, failing_user_email=None):
        self._failing_user_email = failing_user_email
        self.revocations = []

    def revoke_access(self, group_id, google_email):
        if google_email == self._failing_user_email:
            raise RuntimeError("Google unavailable")
        self.revocations.append((group_id, google_email))


def test_next_admin_reconciliation_is_sunday_at_20_moscow_time():
    before = datetime(2026, 9, 6, 19, 30, tzinfo=MOSCOW_TIMEZONE)
    after = datetime(2026, 9, 6, 20, 1, tzinfo=MOSCOW_TIMEZONE)

    assert next_admin_reconciliation(before) == datetime(
        2026, 9, 6, 20, tzinfo=MOSCOW_TIMEZONE
    )
    assert next_admin_reconciliation(after) == datetime(
        2026, 9, 13, 20, tzinfo=MOSCOW_TIMEZONE
    )


def test_next_admin_reconciliation_requires_timezone_aware_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        next_admin_reconciliation(datetime(2026, 9, 6, 19, 30))


def test_reconciliation_revokes_only_departed_admins(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("current", 1), -100001)
    admins.add_admin(Admin("departed", 2), -100001)
    admins.add_admin(Admin("unchecked", 3), -100001)
    admins.set_clan_admin_google_email(2, -100001, "departed@example.com")
    admins.set_clan_admin_google_email(3, -100001, "unchecked@example.com")
    report = RecordingReport()
    bot = MembershipBot(
        {
            (-100001, 1): "member",
            (-100001, 2): "left",
            (-100001, 3): RuntimeError("Telegram unavailable"),
        }
    )

    result = reconcile_clan_admins(bot, groups, admins, report)

    assert result.current == 1
    assert result.revoked == 1
    assert result.check_failed == 1
    assert result.revoke_failed == 0
    assert report.revocations == [(-100001, "departed@example.com")]
    assert admins.is_clan_admin(1, -100001)
    assert not admins.is_clan_admin(2, -100001)
    assert admins.is_clan_admin(3, -100001)
    connection.close()


def test_reconciliation_keeps_acl_when_google_revocation_fails(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("departed", 2), -100001)
    admins.set_clan_admin_google_email(2, -100001, "departed@example.com")
    report = RecordingReport("departed@example.com")
    bot = MembershipBot({(-100001, 2): "left"})

    result = reconcile_clan_admins(bot, groups, admins, report)

    assert result.current == 0
    assert result.revoked == 0
    assert result.check_failed == 0
    assert result.revoke_failed == 1
    assert admins.is_clan_admin(2, -100001)
    connection.close()
