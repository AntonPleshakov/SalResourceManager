from types import SimpleNamespace

from db.access_group import AccessGroup, AccessGroupDB
from db.admins import Admin, AdminsDB
from db.database import Database
from db.user_data import UserDataDB
from tg.clans import sync_migrated_clan_titles


def test_accounts_are_owned_and_filtered_by_clan(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    users = UserDataDB(connection)

    alpha = users.add_account(42, "player", "Alpha hero", clan_id=-100001)
    beta = users.add_account(42, "player", "Beta hero", clan_id=-100002)

    assert alpha.clan_id == -100001
    assert alpha.clan_title == "Alpha"
    assert beta.clan_id == -100002
    assert [user.tag.value for user in users.get_clan_users(-100001)] == [
        "Alpha hero"
    ]
    assert [user.tag.value for user in users.get_clan_users(-100002)] == [
        "Beta hero"
    ]
    connection.close()


def test_detached_account_keeps_data_and_can_move_to_another_clan(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    users = UserDataDB(connection)
    account = users.add_account(42, "player", "Hero", clan_id=-100001)
    users.set_value(
        42,
        "player",
        "hammers",
        1234,
        account_id=account.account_id,
    )

    assert users.detach_accounts_from_clan(42, -100001) == 1
    detached = users.get_active_account(42)
    assert detached is not None
    assert detached.clan_id is None
    stored = users.get_user(42, account.account_id)
    assert stored is not None
    assert stored.hammers.value == 1234
    assert users.get_assigned_user(42, account.account_id) is None
    assert [user.account_id.value for user in users.get_users()] == [
        account.account_id
    ]
    assert users.get_clan_users(-100001) == []
    assert connection.fetch_one(
        "SELECT hammers FROM user_data WHERE account_id = ?",
        (account.account_id,),
    ) == (1234,)

    moved = users.move_account(42, account.account_id, -100002)

    assert moved.clan_id == -100002
    assigned = users.get_assigned_user(42, account.account_id)
    assert assigned is not None
    assert assigned.hammers.value == 1234
    connection.close()


def test_account_requires_explicit_clan_when_several_are_registered(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")

    try:
        UserDataDB(connection).add_account(42, "player", "Hero")
    except ValueError as error:
        assert str(error) == "Выберите клан игрового аккаунта"
    else:
        raise AssertionError("An account without a clan must be rejected")
    connection.close()


def test_administrator_permissions_and_active_clan_are_scoped(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("owner", 42), -100001)
    admins.add_admin(Admin("owner", 42), -100002)
    admins.add_admin(Admin("alpha_admin", 77), -100001)

    assert admins.is_admin(42)
    assert admins.is_admin(42, -100001)
    assert admins.is_admin(42, -100002)
    assert admins.is_admin(77, -100001)
    assert not admins.is_admin(77, -100002)

    admins.select_group(42, -100002)
    assert admins.get_active_group(42) == AccessGroup(-100002, "Beta")
    assert admins.get_clans(42) == [
        AccessGroup(-100002, "Beta"),
        AccessGroup(-100001, "Alpha"),
    ]
    assert [admin.user_id.value for admin in admins.get_admins(-100001)] == [
        42,
        77,
    ]
    assert [admin.user_id.value for admin in admins.get_admins(-100002)] == [42]

    admins.del_admin(42, -100002)
    assert admins.is_admin(42)
    assert not admins.is_admin(42, -100002)
    assert admins.get_active_group(42) == AccessGroup(-100001, "Alpha")
    connection.close()


def test_active_clan_falls_back_to_an_administered_clan(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100001)
    connection.run_in_transaction(
        lambda db: db.execute(
            "UPDATE admins SET active_group_id = ? WHERE user_id = ?",
            (-100002, 42),
        )
    )

    assert admins.get_active_group(42) == AccessGroup(-100001, "Alpha")
    connection.close()


def test_only_migrated_clan_title_is_loaded_from_telegram_once(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    connection.run_in_transaction(
        lambda db: db.execute(
            "INSERT INTO clans (group_id, title, title_needs_sync) "
            "VALUES (?, ?, 1)",
            (-100001, "Клан -100001"),
        )
    )
    groups.add_group(-100002, "Manually registered")

    class FakeBot:
        def __init__(self):
            self.requests = []

        def get_chat(self, group_id):
            self.requests.append(group_id)
            return SimpleNamespace(title="Telegram title")

    bot = FakeBot()
    sync_migrated_clan_titles(bot, groups)
    sync_migrated_clan_titles(bot, groups)

    assert bot.requests == [-100001]
    assert groups.get_group(-100001).title == "Telegram title"
    assert groups.get_group(-100002).title == "Manually registered"
    assert groups.get_groups_requiring_title_sync() == []
    connection.close()


def test_manual_clan_rename_never_requires_telegram_sync(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Old title")

    renamed = groups.rename_group(-100001, "  New   title  ")

    assert renamed.title == "New title"
    assert groups.get_group(-100001).title == "New title"
    assert groups.get_groups_requiring_title_sync() == []
    connection.close()
