import sqlite3
from html import unescape
from pathlib import Path
import re

import pytest
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.database import Database
from db.access_group import AccessGroupDB
from db.migration_runner import MIGRATIONS_DIR, apply_migrations
from db.user_data import UserDataDB
from tg.user_data.accounts import (
    accounts_menu,
    confirm_delete,
    create_initial_account,
    leave_clan,
    request_add,
    request_delete,
    request_move,
    move_account,
    select_account,
)
from tg.user_data.account.routing import open_destination


def make_callback(data: str) -> CallbackQuery:
    telegram_user = User(42, False, "Tester", username="telegram_user")
    chat = Chat(42, "private")
    message = Message(1, telegram_user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", telegram_user, data, "", None, message)


def make_message(text: str = "value") -> Message:
    telegram_user = User(42, False, "Tester", username="telegram_user")
    chat = Chat(42, "private")
    return Message(2, telegram_user, 0, chat, "text", {"text": text}, None)


class FakeBot:
    def __init__(self):
        self.edited = []
        self.sent = []
        self.callback_answers = []

    def delete_state(self, _user_id):
        pass

    def edit_message_text(
        self,
        text=None,
        chat_id=None,
        message_id=None,
        reply_markup=None,
        rich_message=None,
    ):
        content = rich_message.html if rich_message is not None else text
        self.edited.append((content, chat_id, message_id, reply_markup))

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((text, chat_id, reply_markup))

    def send_rich_message(self, chat_id, rich_message):
        self.sent.append((rich_message.html, chat_id, None))

    def answer_callback_query(self, *args, **kwargs):
        self.callback_answers.append((args, kwargs))

    def get_chat_member(self, group_id, user_id):
        status = "member" if group_id == -100123 else "left"
        return type(
            "Member",
            (),
            {"status": status, "tag": "Clan hero"},
        )()


def callback_data(markup):
    if isinstance(markup, str):
        return re.findall(r'<tg-button[^>]+data="([^"]+)"', markup)
    return [
        button.callback_data for row in markup.keyboard for button in row
    ]


def callback_texts(markup):
    if isinstance(markup, str):
        return [
            unescape(text)
            for text in re.findall(
                r"<tg-button\s[^>]*>(.*?)</tg-button>", markup
            )
        ]
    return [button.text for row in markup.keyboard for button in row]


def register_test_clan(connection):
    AccessGroupDB(connection).add_group(-100123, "Test clan")


def test_resources_are_isolated_and_active_account_can_be_switched(tmp_path):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)

    first = database.add_account(42, "telegram_user", "Main")
    database.set_value(
        42,
        "telegram_user",
        "hammers",
        1_000,
        account_id=first.account_id,
    )
    second = database.add_account(42, "telegram_user", "Alt")
    database.set_value(
        42,
        "telegram_user",
        "hammers",
        2_000,
        account_id=second.account_id,
    )

    assert database.get_user(42).tag.value == "Alt"
    assert database.get_user(42).hammers.value == 2_000

    database.select_account(42, first.account_id)

    assert database.get_user(42).tag.value == "Main"
    assert database.get_user(42).hammers.value == 1_000
    assert [user.tag.value for user in database.get_users()] == ["Main", "Alt"]
    assert database.get_account_counts() == {42: 2}
    connection.close()


def test_clan_account_counts_include_registered_clans_without_accounts(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main", clan_id=-100123)
    database.add_account(42, "telegram_user", "Alt", clan_id=-100123)
    database.add_account(77, "another_user", "Other", clan_id=-100123)

    assert database.get_clan_account_counts() == [
        (-100123, "Alpha", 2, 3),
        (-100456, "Beta", 0, 0),
    ]
    connection.close()


def test_new_account_clan_picker_only_shows_memberships(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    bot = FakeBot()

    request_add(make_callback("accounts/add/accounts"), bot)

    assert callback_data(bot.edited[-1][0]) == [
        "accounts/add/accounts/clan/-100123",
        "accounts",
    ]
    connection.close()


def test_active_account_can_move_only_to_a_current_membership(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    account = database.add_account(
        42, "telegram_user", "Main", clan_id=-100456
    )
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    request_move(make_callback("accounts/move"), bot)
    assert callback_data(bot.edited[-1][0]) == [
        f"accounts/move/{account.account_id}/clan/-100123",
        "accounts",
    ]

    move_account(
        make_callback(
            f"accounts/move/{account.account_id}/clan/-100123"
        ),
        bot,
    )
    assert database.get_active_account(42).clan_id == -100123

    move_account(
        make_callback(
            f"accounts/move/{account.account_id}/clan/-100456"
        ),
        bot,
    )
    assert database.get_active_account(42).clan_id == -100123
    assert bot.callback_answers[-1][1]["show_alert"] is True
    connection.close()


def test_clan_actions_separate_moving_and_leaving(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    account = database.add_account(
        42, "telegram_user", "Main", clan_id=-100123
    )
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)

    class BothClansBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            return type("Member", (), {"status": "member"})()

    bot = BothClansBot()

    accounts_menu(make_callback("accounts"), bot)

    assert "🏰 Сменить клан" in callback_texts(bot.edited[-1][0])
    assert "🔗 Отвязать от клана" in callback_texts(bot.edited[-1][0])

    request_move(make_callback("accounts/move"), bot)

    assert callback_data(bot.edited[-1][0]) == [
        f"accounts/move/{account.account_id}/clan/-100456",
        "accounts",
    ]
    connection.close()


def test_leaving_clan_detaches_account_and_preserves_data(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    account = database.add_account(42, "telegram_user", "Main")
    database.set_value(
        42,
        "telegram_user",
        "hammers",
        1234,
        account_id=account.account_id,
    )
    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: AccessGroupDB(connection)
    )
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    leave_clan(
        make_callback(f"accounts/move/{account.account_id}/leave/accounts"),
        bot,
    )

    assert database.get_active_account(42).clan_id == -100123
    assert callback_data(bot.edited[-1][0]) == [
        f"accounts/move/{account.account_id}/leave/confirm/accounts",
        "accounts",
    ]

    leave_clan(
        make_callback(
            f"accounts/move/{account.account_id}/leave/confirm/accounts"
        ),
        bot,
    )

    assert database.get_active_account(42).clan_id is None
    assert database.get_user(42, account.account_id).hammers.value == 1234
    assert "Данные аккаунта сохранены" in bot.edited[-1][0]
    connection.close()


def test_accounts_menu_uses_explicit_clan_actions(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    detached = database.add_account(
        42, "telegram_user", "Detached", clan_id=-100456
    )
    database.add_account(42, "telegram_user", "Assigned", clan_id=-100123)
    database.detach_account_from_clan(42, detached.account_id)
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts"), bot)

    assert "Detached" in bot.edited[-1][0]
    assert "клан не выбран" in bot.edited[-1][0]
    assert "Выбрать аккаунт" in callback_texts(bot.edited[-1][0])
    assert "🏰 Сменить клан" not in callback_texts(bot.edited[-1][0])
    assert "🔗 Отвязать от клана" in callback_texts(bot.edited[-1][0])

    database.select_account(42, detached.account_id)
    accounts_menu(make_callback("accounts"), bot)

    assert "🏰 Выбрать клан" in callback_texts(bot.edited[-1][0])

    class NoClansBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            return type("Member", (), {"status": "left"})()

    no_clans_bot = NoClansBot()
    accounts_menu(make_callback("accounts"), no_clans_bot)
    no_clan_actions = callback_texts(no_clans_bot.edited[-1][0])
    assert "🏰 Выбрать клан" not in no_clan_actions
    connection.close()


def test_initial_account_is_created_in_selected_clan(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    create_initial_account(make_callback("accounts/create/-100123"), bot)

    account = database.get_active_account(42)
    assert account is not None
    assert account.tag == "Clan hero"
    assert account.clan_id == -100123
    assert "Добро пожаловать" in bot.edited[-1][0]
    connection.close()


def test_reminder_preference_defaults_to_enabled_and_filters_users(tmp_path):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    database.add_account(77, "another_user", "Other")

    assert database.reminders_enabled(42) is True
    reminder_user_ids = {
        user.user_id.value
        for user in database.get_assigned_users_with_reminders_enabled()
    }
    assert reminder_user_ids == {42, 77}

    database.set_reminders_enabled(42, False)

    assert database.reminders_enabled(42) is False
    reminder_user_ids = {
        user.user_id.value
        for user in database.get_assigned_users_with_reminders_enabled()
    }
    assert reminder_user_ids == {77}
    assert {user.user_id.value for user in database.get_users()} == {42, 77}
    connection.close()


def test_account_selector_returns_to_resource_screen_after_switch(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    first = database.add_account(42, "telegram_user", "Main")
    second = database.add_account(42, "telegram_user", "Alt")
    groups = AccessGroupDB(connection)
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts/resources"), bot)

    menu_buttons = callback_data(bot.edited[-1][0])
    assert "Аккаунт: <b>Alt</b>" in bot.edited[-1][0]
    assert menu_buttons[0] == f"accounts/select/resources/{first.account_id}"
    assert f"accounts/select/resources/{second.account_id}" not in menu_buttons
    assert "accounts/add/resources" in menu_buttons
    assert "accounts/delete/menu/resources" in menu_buttons
    assert "✏️ Переименовать" in callback_texts(bot.edited[-1][0])
    assert menu_buttons[-1] == "resources"

    select_account(
        make_callback(f"accounts/select/resources/{first.account_id}"), bot
    )

    assert database.get_active_account(42).account_id == first.account_id
    assert "Аккаунт: <b>Main</b>" in bot.edited[-1][0]
    assert 'data="user_data/edit/hammers"' in bot.edited[-1][0]

    select_account(
        make_callback(f"accounts/select/resources/{first.account_id}"), bot
    )

    assert "<h2>Ресурсы</h2>" in bot.edited[-1][0]
    assert not bot.callback_answers
    connection.close()


def test_data_account_selector_hides_accounts_without_a_clan(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    detached = database.add_account(
        42, "telegram_user", "Detached", make_active=False
    )
    database.detach_account_from_clan(42, detached.account_id)
    monkeypatch.setattr(
        "tg.user_data.get_access_group_db", lambda: AccessGroupDB(connection)
    )
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts/resources"), bot)

    assert (
        f"accounts/select/resources/{detached.account_id}"
        not in callback_data(bot.edited[-1][0])
    )

    accounts_menu(make_callback("accounts"), bot)

    assert (
        f"accounts/select/accounts/{detached.account_id}"
        in callback_data(bot.edited[-1][0])
    )
    connection.close()


def test_stale_data_account_selection_detaches_and_prompts_for_clan(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    groups.add_group(-100456, "Beta")
    database = UserDataDB(connection)
    active = database.add_account(
        42, "telegram_user", "Main", clan_id=-100123
    )
    stale = database.add_account(
        42,
        "telegram_user",
        "Old clan account",
        clan_id=-100456,
        make_active=False,
    )
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    select_account(
        make_callback(f"accounts/select/resources/{stale.account_id}"), bot
    )

    assert database.get_active_account(42).account_id == active.account_id
    assert next(
        account
        for account in database.get_accounts(42)
        if account.account_id == stale.account_id
    ).clan_id is None
    assert "Выберите клан аккаунта" in bot.edited[-1][0]
    assert "<h2>Ресурсы</h2>" not in bot.edited[-1][0]
    assert callback_data(bot.edited[-1][0])[-1] == "accounts/resources"
    assert all(
        callback.endswith("/resources")
        for callback in callback_data(bot.edited[-1][0])[:-1]
    )
    connection.close()


def test_account_menu_fails_closed_when_membership_check_fails(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    account = database.add_account(42, "telegram_user", "Secret account")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)

    class FailingBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            raise RuntimeError("Telegram unavailable")

    bot = FailingBot()

    accounts_menu(make_callback("accounts"), bot)

    assert bot.edited[-1][0] == (
        "Не удалось проверить участие в клане. Попробуйте ещё раз позже."
    )
    assert "Secret account" not in bot.edited[-1][0]
    assert database.get_active_account(42).clan_id == account.clan_id
    connection.close()


def test_account_selection_fails_closed_when_membership_check_fails(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    candidate = database.add_account(42, "telegram_user", "Candidate")
    active = database.add_account(42, "telegram_user", "Current")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)

    class FailingBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            raise RuntimeError("Telegram unavailable")

    bot = FailingBot()

    select_account(
        make_callback(
            f"accounts/select/resources/{candidate.account_id}"
        ),
        bot,
    )

    assert database.get_active_account(42).account_id == active.account_id
    assert bot.edited[-1][0] == (
        "Не удалось проверить участие в клане. Попробуйте ещё раз позже."
    )
    connection.close()


def test_message_destination_sends_resource_menu(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    groups = AccessGroupDB(connection)
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    open_destination(
        make_message(),
        bot,
        "resources",
        "✅ Аккаунт сохранён.",
    )

    assert bot.edited == []
    assert len(bot.sent) == 1
    assert "✅ Аккаунт сохранён." in bot.sent[0][0]
    assert "<h2>Ресурсы</h2>" in bot.sent[0][0]
    connection.close()


def test_repeated_account_selection_does_not_edit_message(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    account = database.add_account(42, "telegram_user", "Main")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    select_account(
        make_callback(f"accounts/select/accounts/{account.account_id}"), bot
    )

    assert database.get_active_account(42).account_id == account.account_id
    assert bot.edited == []
    assert bot.callback_answers == [
        (("callback-1", "Аккаунт уже выбран"), {})
    ]
    connection.close()


def test_single_account_menu_does_not_offer_deletion(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    groups = AccessGroupDB(connection)
    monkeypatch.setattr("tg.user_data.get_access_group_db", lambda: groups)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts"), bot)

    assert "accounts/delete" not in callback_data(bot.edited[-1][0])
    connection.close()


def test_delete_selector_only_lists_inactive_accounts(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    first = database.add_account(42, "telegram_user", "Main")
    second = database.add_account(42, "telegram_user", "Alt")
    active = database.add_account(42, "telegram_user", "Current")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    request_delete(make_callback("accounts/delete/menu/accounts"), bot)

    menu_buttons = callback_data(bot.edited[-1][0])
    assert menu_buttons == [
        f"accounts/delete/confirm/{first.account_id}/accounts",
        f"accounts/delete/confirm/{second.account_id}/accounts",
        "accounts",
    ]
    assert (
        f"accounts/delete/confirm/{active.account_id}/accounts"
        not in menu_buttons
    )

    confirm_delete(
        make_callback(
            f"accounts/delete/confirm/{first.account_id}/accounts"
        ),
        bot,
    )

    assert "Удалить аккаунт «Main»?" in bot.edited[-1][0]
    assert callback_data(bot.edited[-1][0]) == [
        f"accounts/delete/{first.account_id}/accounts",
        "accounts/delete/menu/accounts",
    ]
    connection.close()


def test_game_accounts_can_be_renamed_and_deleted(tmp_path):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    first = database.add_account(42, "telegram_user", "Main")
    second = database.add_account(42, "telegram_user", "Alt")

    renamed = database.rename_account(42, second.account_id, "Second hero")
    assert renamed.tag == "Second hero"

    with pytest.raises(ValueError, match="уже существует"):
        database.rename_account(42, second.account_id, "Main")

    database.delete_account(42, first.account_id)
    assert database.get_active_account(42).account_id == second.account_id

    with pytest.raises(ValueError, match="Активный аккаунт нельзя удалить"):
        database.delete_account(42, second.account_id)
    connection.close()


def test_account_operations_cannot_access_another_telegram_users_account(tmp_path):
    connection = Database(tmp_path / "database.db")
    register_test_clan(connection)
    database = UserDataDB(connection)
    чужой = database.add_account(7, "other", "Other")

    with pytest.raises(ValueError, match="не найден"):
        database.select_account(42, чужой.account_id)
    with pytest.raises(ValueError, match="не найден"):
        database.rename_account(42, чужой.account_id, "Stolen")
    with pytest.raises(ValueError, match="не найден"):
        database.delete_account(42, чужой.account_id)
    connection.close()


def test_migration_turns_existing_user_data_into_first_game_account(tmp_path):
    partial = tmp_path / "migrations"
    partial.mkdir()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql"))[:7]:
        (partial / migration.name).write_text(
            migration.read_text(encoding="utf-8"), encoding="utf-8"
        )
    database_path = tmp_path / "database.db"
    with sqlite3.connect(database_path) as connection:
        apply_migrations(connection, partial)
        connection.execute(
            "INSERT INTO access_group (singleton, group_id) VALUES (1, ?)",
            (-100123,),
        )
        connection.execute(
            "INSERT INTO user_data ("
            "user_id, username, tag, mount_keys, mount_keys_updated_on, "
            "skills, skills_updated_on, shells, shells_updated_on, "
            "hammers, hammers_updated_on, pets, pets_updated_on, "
            "unmerged_mounts, unmerged_mounts_updated_on, forge_level, "
            "forge_level_updated_on, skill_summon_cost, "
            "skill_summon_cost_updated_on, extra_egg_chance, "
            "extra_egg_chance_updated_on, mount_summon_cost, "
            "mount_summon_cost_updated_on, extra_mount_chance, "
            "extra_mount_chance_updated_on"
            ") VALUES (?, ?, ?, ?, '', ?, '', ?, '', ?, '', ?, '', ?, '', ?, '', "
            "?, '', ?, '', ?, '', ?, '')",
            (42, "telegram_user", "OldHero", 11, 12, 13, 14, 15, 16, 7, 8, 9, 10, 11),
        )

    connection = Database(database_path)
    database = UserDataDB(connection)
    migrated = database.get_user(42)

    assert migrated is not None
    assert migrated.username.value == "telegram_user"
    assert migrated.tag.value == "OldHero"
    assert migrated.mount_keys.value == 11
    assert migrated.pets.value == 15
    assert database.get_active_account(42).tag == "OldHero"
    connection.close()
