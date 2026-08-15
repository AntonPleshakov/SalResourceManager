import sqlite3
from pathlib import Path

import pytest
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.database import Database
from db.migration_runner import MIGRATIONS_DIR, apply_migrations
from db.user_data import UserDataDB
from tg.user_data.accounts import (
    accounts_menu,
    confirm_delete,
    request_delete,
    select_account,
)


def make_callback(data: str) -> CallbackQuery:
    telegram_user = User(42, False, "Tester", username="telegram_user")
    chat = Chat(42, "private")
    message = Message(1, telegram_user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", telegram_user, data, "", None, message)


class FakeBot:
    def __init__(self):
        self.edited = []
        self.sent = []
        self.callback_answers = []

    def delete_state(self, _user_id):
        pass

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edited.append((text, chat_id, message_id, reply_markup))

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((text, chat_id, reply_markup))

    def answer_callback_query(self, *args, **kwargs):
        self.callback_answers.append((args, kwargs))


def callback_data(markup):
    return [
        button.callback_data for row in markup.keyboard for button in row
    ]


def test_resources_are_isolated_and_active_account_can_be_switched(tmp_path):
    connection = Database(tmp_path / "database.db")
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


def test_reminder_preference_defaults_to_enabled_and_filters_users(tmp_path):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    database.add_account(77, "another_user", "Other")

    assert database.reminders_enabled(42) is True
    reminder_user_ids = {
        user.user_id.value
        for user in database.get_users_with_reminders_enabled()
    }
    assert reminder_user_ids == {42, 77}

    database.set_reminders_enabled(42, False)

    assert database.reminders_enabled(42) is False
    reminder_user_ids = {
        user.user_id.value
        for user in database.get_users_with_reminders_enabled()
    }
    assert reminder_user_ids == {77}
    assert {user.user_id.value for user in database.get_users()} == {42, 77}
    connection.close()


def test_account_selector_returns_to_resource_screen_after_switch(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)
    first = database.add_account(42, "telegram_user", "Main")
    second = database.add_account(42, "telegram_user", "Alt")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts/resources"), bot)

    menu_buttons = callback_data(bot.edited[-1][3])
    assert f"Активный аккаунт: <b>Alt</b>" in bot.edited[-1][0]
    assert menu_buttons[0] == f"accounts/select/resources/{first.account_id}"
    assert f"accounts/select/resources/{second.account_id}" not in menu_buttons
    assert "accounts/add/resources" in menu_buttons
    assert "accounts/delete" in menu_buttons
    assert "✏️ Переименовать" in [
        button.text for row in bot.edited[-1][3].keyboard for button in row
    ]
    assert menu_buttons[-1] == "resources"

    select_account(
        make_callback(f"accounts/select/resources/{first.account_id}"), bot
    )

    assert database.get_active_account(42).account_id == first.account_id
    assert "Игровой аккаунт: <b>Main</b>" in bot.edited[-1][0]
    connection.close()


def test_repeated_account_selection_does_not_edit_message(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
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
    database = UserDataDB(connection)
    database.add_account(42, "telegram_user", "Main")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    accounts_menu(make_callback("accounts"), bot)

    assert "accounts/delete" not in callback_data(bot.edited[-1][3])
    connection.close()


def test_delete_selector_only_lists_inactive_accounts(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    database = UserDataDB(connection)
    first = database.add_account(42, "telegram_user", "Main")
    second = database.add_account(42, "telegram_user", "Alt")
    active = database.add_account(42, "telegram_user", "Current")
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    bot = FakeBot()

    request_delete(make_callback("accounts/delete"), bot)

    menu_buttons = callback_data(bot.edited[-1][3])
    assert menu_buttons == [
        f"accounts/delete/confirm/{first.account_id}",
        f"accounts/delete/confirm/{second.account_id}",
        "accounts",
    ]
    assert f"accounts/delete/confirm/{active.account_id}" not in menu_buttons

    confirm_delete(
        make_callback(f"accounts/delete/confirm/{first.account_id}"), bot
    )

    assert "Удалить аккаунт <b>Main</b>?" in bot.edited[-1][0]
    assert callback_data(bot.edited[-1][3]) == [
        f"accounts/delete/{first.account_id}",
        "accounts/delete",
    ]
    connection.close()


def test_game_accounts_can_be_renamed_and_deleted(tmp_path):
    connection = Database(tmp_path / "database.db")
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
