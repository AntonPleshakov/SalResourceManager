from contextlib import nullcontext
from pathlib import Path

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.admins import Admin
from tg.admins.add_admin import add_admins_approved
from tg.admins.del_admin import del_admin_approved


def make_callback(data: str = "approved") -> CallbackQuery:
    user = User(42, False, "Requester", username="requester")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


class FakeBot:
    def __init__(self, data=None):
        self.data = data or {}
        self.deleted_states = []
        self.callback_answers = []
        self.send_attempts = []

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def send_message(self, user_id, text):
        self.send_attempts.append((user_id, text))
        raise RuntimeError("bot was blocked")

    def answer_callback_query(self, callback_query_id, text):
        self.callback_answers.append((callback_query_id, text))


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
