from contextlib import nullcontext
from pathlib import Path

import pytest
from telebot.types import (
    CallbackQuery,
    Chat,
    Message,
    ReplyKeyboardRemove,
    SharedUser,
    User,
    UsersShared,
)

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.access_group import AccessGroup, AccessGroupDB
from db.admins import Admin, AdminsDB
from db.database import Database
from tg.admins.add_admin import (
    add_admins_approved,
    add_admins_confirmation,
    cancel_add_admins,
)
from tg.admins.common import (
    AdminAccessCheckError,
    AdminAccessError,
    require_admin_access,
)
from tg.admins.del_admin import del_admin_approved, del_admin_options
from tg.admins.rename_clan import rename_clan, request_clan_rename


def make_callback(data: str = "approved") -> CallbackQuery:
    user = User(42, False, "Requester", username="requester")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def make_message(text: str = "") -> Message:
    user = User(42, False, "Requester", username="requester")
    return Message(
        1,
        user,
        0,
        Chat(42, "private"),
        "text",
        {"text": text},
        None,
    )


class FakeBot:
    def __init__(self, data=None):
        self.data = data or {}
        self.deleted_states = []
        self.callback_answers = []
        self.send_attempts = []
        self.edits = []
        self.states = []

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def send_message(self, user_id, text):
        self.send_attempts.append((user_id, text))
        raise RuntimeError("bot was blocked")

    def answer_callback_query(self, callback_query_id, text):
        self.callback_answers.append((callback_query_id, text))

    def edit_message_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def get_chat_member(self, group_id, user_id):
        return type("Member", (), {"status": "member"})()


class RecordingBot:
    def __init__(self):
        self.data = {}
        self.deleted_states = []
        self.sent = []
        self.states = []

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def get_chat_member(self, group_id, user_id):
        return type("Member", (), {"status": "member"})()


class RenameClanBot:
    def __init__(self):
        self.data = {}
        self.states = []
        self.deleted_states = []
        self.edits = []
        self.sent = []

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def edit_message_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    def get_chat_member(self, group_id, user_id):
        return type("Member", (), {"status": "member"})()


def test_delete_admin_options_exclude_requester(monkeypatch):
    admins = [
        Admin("requester", 42),
        Admin("first", 1),
        Admin("second", 101),
    ]
    fake_db = type(
        "FakeAdminsDB",
        (),
        {"get_clan_admins": lambda _, group_id: admins},
    )()
    monkeypatch.setattr("tg.admins.del_admin.get_admins_db", lambda: fake_db)
    monkeypatch.setattr(
        "tg.admins.del_admin.get_active_admin_group",
        lambda bot, user_id: AccessGroup(-100123, "Test clan"),
    )
    bot = FakeBot()

    del_admin_options(make_callback(), bot)

    keyboard = bot.edits[0][1]["reply_markup"]
    callback_data = [
        button.callback_data
        for row in keyboard.keyboard
        for button in row
    ]
    assert callback_data == ["1", "101", "admins"]
    assert bot.data["admin_group_title"] == "Test clan"


def test_add_admins_finishes_when_private_notifications_fail(monkeypatch):
    new_admins = [Admin("one", 101), Admin("two", 102)]
    added = []
    homes = []
    monkeypatch.setattr(
        "tg.admins.add_admin.home", lambda callback_query, bot: homes.append(callback_query)
    )
    fake_db = type(
        "FakeAdminsDB",
        (),
        {
            "is_clan_admin": lambda _, user_id, group_id: True,
            "add_admin": lambda _, admin, group_id: added.append(admin),
        },
    )()
    monkeypatch.setattr(
        "tg.admins.add_admin.get_admins_db", lambda: fake_db
    )
    bot = FakeBot(
        {"new_admins": new_admins, "admin_group_id": -100123}
    )
    callback = make_callback()

    add_admins_approved(callback, bot)

    assert added == new_admins
    assert [attempt[0] for attempt in bot.send_attempts] == [101, 102]
    assert bot.callback_answers == [("callback-1", "Администраторы добавлены")]
    assert homes == [callback]


def test_add_admins_result_names_rejected_users(monkeypatch):
    new_admins = [Admin("accepted", 101), Admin("rejected", 102)]
    added = []
    homes = []
    fake_db = type(
        "FakeAdminsDB",
        (),
        {
            "is_clan_admin": lambda _, user_id, group_id: True,
            "add_admin": lambda _, admin, group_id: added.append(admin),
        },
    )()
    monkeypatch.setattr("tg.admins.add_admin.get_admins_db", lambda: fake_db)
    monkeypatch.setattr(
        "tg.admins.add_admin.home", lambda callback_query, bot: homes.append(callback_query)
    )
    bot = FakeBot({"new_admins": new_admins, "admin_group_id": -100123})
    bot.get_chat_member = lambda group_id, user_id: type(
        "Member",
        (),
        {"status": "left" if user_id == 102 else "member"},
    )()
    callback = make_callback()

    add_admins_approved(callback, bot)

    assert added == [new_admins[0]]
    assert bot.callback_answers == [
        (
            "callback-1",
            "Администраторы добавлены\n"
            "rejected не добавлен: не состоит в клане",
        )
    ]
    assert homes == [callback]


def test_add_admins_omits_rejection_details_when_all_users_are_rejected(
    monkeypatch,
):
    new_admins = [Admin("rejected", 102)]
    fake_db = type(
        "FakeAdminsDB",
        (),
        {
            "is_clan_admin": lambda _, user_id, group_id: True,
            "add_admin": lambda _, admin, group_id: None,
        },
    )()
    monkeypatch.setattr("tg.admins.add_admin.get_admins_db", lambda: fake_db)
    monkeypatch.setattr("tg.admins.add_admin.home", lambda callback_query, bot: None)
    bot = FakeBot({"new_admins": new_admins, "admin_group_id": -100123})
    bot.get_chat_member = lambda group_id, user_id: type(
        "Member", (), {"status": "left" if user_id == 102 else "member"}
    )()

    add_admins_approved(make_callback(), bot)

    assert bot.callback_answers == [
        ("callback-1", "Администраторы не добавлены")
    ]


def test_add_admins_can_be_cancelled_and_removes_reply_keyboard(monkeypatch):
    homes = []
    monkeypatch.setattr(
        "tg.admins.add_admin.home", lambda message, bot: homes.append(message)
    )
    bot = RecordingBot()
    message = make_message("Отмена")

    cancel_add_admins(message, bot)

    assert bot.deleted_states == [42]
    assert bot.sent[0][1] == "Добавление администраторов отменено."
    assert isinstance(bot.sent[0][2]["reply_markup"], ReplyKeyboardRemove)
    assert homes == [message]


def test_selecting_admins_removes_reply_keyboard_before_confirmation(monkeypatch):
    monkeypatch.setattr(
        "tg.admins.add_admin.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {"is_clan_admin": lambda _, user_id, group_id: True},
        )(),
    )
    bot = RecordingBot()
    bot.data["admin_group_id"] = -100123
    message = make_message()
    message.users_shared = UsersShared(
        request_id=0,
        users=[SharedUser(user_id=101, username="candidate")],
    )

    add_admins_confirmation(message, bot)

    assert isinstance(bot.sent[0][2]["reply_markup"], ReplyKeyboardRemove)
    assert bot.sent[1][1] == (
        'Добавить администраторов?\n<a href="tg://user?id=101">candidate</a>'
    )


def test_revoked_admin_cannot_continue_selecting_admins(monkeypatch):
    monkeypatch.setattr(
        "tg.admins.add_admin.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {"is_clan_admin": lambda _, user_id, group_id: False},
        )(),
    )
    bot = RecordingBot()
    bot.data["admin_group_id"] = -100123
    message = make_message()
    message.users_shared = UsersShared(
        request_id=0,
        users=[SharedUser(user_id=101, username="candidate")],
    )

    add_admins_confirmation(message, bot)

    assert bot.deleted_states == [42]
    assert len(bot.sent) == 1
    assert bot.sent[0][1] == "Нет прав администратора выбранного клана."
    assert isinstance(bot.sent[0][2]["reply_markup"], ReplyKeyboardRemove)


def test_delete_admin_finishes_when_private_notification_fails(monkeypatch):
    admin = Admin("former", 101)
    deleted = []
    homes = []
    fake_db = type(
        "FakeAdminsDB",
        (),
        {
            "is_clan_admin": lambda _, user_id, group_id: True,
            "get_clan_admin": lambda _, user_id, group_id: admin,
            "del_clan_admin": lambda _, user_id, group_id: deleted.append(user_id),
        },
    )()
    monkeypatch.setattr("tg.admins.del_admin.get_admins_db", lambda: fake_db)
    monkeypatch.setattr(
        "tg.admins.del_admin.home", lambda callback_query, bot: homes.append(callback_query)
    )
    bot = FakeBot(
        {
            "admin_group_id": -100123,
            "admin_group_title": "Test clan",
        }
    )
    callback = make_callback("approved/101")

    del_admin_approved(callback, bot)

    assert deleted == [101]
    assert bot.send_attempts == [
        (
            101,
            "Ваши права администратора клана «Test clan» были отозваны.",
        )
    ]
    assert bot.callback_answers == [
        ("callback-1", "Права администратора клана отозваны")
    ]
    assert homes == [callback]


def test_admin_can_rename_active_clan(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Old title")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("requester", 42), -100123)
    monkeypatch.setattr(
        "tg.admins.rename_clan.get_access_group_db", lambda: groups
    )
    monkeypatch.setattr("tg.admins.rename_clan.get_admins_db", lambda: admins)
    monkeypatch.setattr(
        "tg.admins.rename_clan.get_active_admin_group",
        lambda bot, user_id: groups.get_group(-100123),
    )
    bot = RenameClanBot()

    request_clan_rename(make_callback("admins/rename_clan"), bot)
    rename_clan(make_message("  New   <clan>  "), bot)

    assert bot.data["rename_clan_group_id"] == -100123
    assert groups.get_group(-100123).title == "New <clan>"
    assert bot.deleted_states == [42]
    assert "New &lt;clan&gt;" in bot.sent[-1][1]
    connection.close()


def test_departed_admin_loses_only_the_departed_clan_acl(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("requester", 42), -100001)
    admins.add_admin(Admin("requester", 42), -100002)

    class MembershipBot:
        def get_chat_member(self, group_id, user_id):
            status = "left" if group_id == -100001 else "member"
            return type("Member", (), {"status": status})()

    with pytest.raises(AdminAccessError, match="больше не состоит"):
        require_admin_access(MembershipBot(), 42, -100001, admins)

    assert not admins.is_clan_admin(42, -100001)
    assert admins.is_clan_admin(42, -100002)
    connection.close()


def test_admin_membership_check_failure_keeps_acl_but_denies_access(tmp_path):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Alpha")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("requester", 42), -100123)

    class FailingBot:
        def get_chat_member(self, group_id, user_id):
            raise RuntimeError("Telegram unavailable")

    with pytest.raises(AdminAccessCheckError, match="Не удалось проверить"):
        require_admin_access(FailingBot(), 42, -100123, admins)

    assert admins.is_clan_admin(42, -100123)
    connection.close()
