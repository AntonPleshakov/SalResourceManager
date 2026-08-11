from contextlib import nullcontext
from pathlib import Path

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

from db.admins import Admin
from tg.admins.add_admin import (
    add_admins_approved,
    add_admins_confirmation,
    cancel_add_admins,
)
from tg.admins.del_admin import del_admin_approved, del_admin_options


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


def test_delete_admin_options_exclude_requester(monkeypatch):
    admins = [
        Admin("requester", 42),
        Admin("first", 1),
        Admin("second", 101),
    ]
    fake_db = type(
        "FakeAdminsDB",
        (),
        {"get_admins": lambda _: admins},
    )()
    monkeypatch.setattr("tg.admins.del_admin.get_admins_db", lambda: fake_db)
    bot = FakeBot()

    del_admin_options(make_callback(), bot)

    keyboard = bot.edits[0][1]["reply_markup"]
    callback_data = [
        button.callback_data
        for row in keyboard.keyboard
        for button in row
    ]
    assert callback_data == ["1", "101", "admins"]


def test_add_admins_finishes_when_private_notifications_fail(monkeypatch):
    new_admins = [Admin("one", 101), Admin("two", 102)]
    added = []
    homes = []
    monkeypatch.setattr(
        "tg.admins.add_admin.get_admins_db",
        lambda: type("FakeAdminsDB", (), {"add_admin": lambda _, admin: added.append(admin)})(),
    )
    monkeypatch.setattr(
        "tg.admins.add_admin.home", lambda callback_query, bot: homes.append(callback_query)
    )
    bot = FakeBot({"new_admins": new_admins})
    callback = make_callback()

    add_admins_approved(callback, bot)

    assert added == new_admins
    assert [attempt[0] for attempt in bot.send_attempts] == [101, 102]
    assert bot.callback_answers == [("callback-1", "Администраторы добавлены")]
    assert homes == [callback]


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


def test_selecting_admins_removes_reply_keyboard_before_confirmation():
    bot = RecordingBot()
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


def test_delete_admin_finishes_when_private_notification_fails(monkeypatch):
    admin = Admin("former", 101)
    deleted = []
    homes = []
    fake_db = type(
        "FakeAdminsDB",
        (),
        {
            "get_admin": lambda _, user_id: admin,
            "del_admin": lambda _, user_id: deleted.append(user_id),
        },
    )()
    monkeypatch.setattr("tg.admins.del_admin.get_admins_db", lambda: fake_db)
    monkeypatch.setattr(
        "tg.admins.del_admin.home", lambda callback_query, bot: homes.append(callback_query)
    )
    bot = FakeBot()
    callback = make_callback("approved/101")

    del_admin_approved(callback, bot)

    assert deleted == [101]
    assert [attempt[0] for attempt in bot.send_attempts] == [101]
    assert bot.callback_answers == [("callback-1", "Права администратора отозваны")]
    assert homes == [callback]
