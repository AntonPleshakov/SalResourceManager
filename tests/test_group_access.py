from pathlib import Path
from types import SimpleNamespace

from telebot.handler_backends import CancelUpdate
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from tg.access import (
    ACCESS_CHECK_FAILED_MESSAGE,
    ACCESS_DENIED_ALERT_MESSAGE,
    ACCESS_DENIED_MESSAGE,
    ACCESS_GROUP_NOT_REGISTERED_MESSAGE,
    GroupAccessMiddleware,
    is_group_member,
)
from tg.group_registration import (
    BOT_NOT_ADMIN_MESSAGE,
    NOT_ADMIN_MESSAGE,
    REGISTRATION_SUCCESS_MESSAGE,
    register_access_group,
)


def make_message(user_id=42, chat_type="private", text="hello"):
    user = User(user_id, False, "Tester", username="tester")
    chat_id = user_id if chat_type == "private" else -100123
    chat = Chat(chat_id, chat_type, title="Test group")
    return Message(1, user, 0, chat, "text", {"text": text}, None)


class FakeAccessGroupDB:
    def __init__(self, group_id=None):
        self.group_id = group_id

    def get_group_id(self):
        return self.group_id

    def set_group_id(self, group_id):
        self.group_id = group_id


class FakeBot:
    def __init__(self, member=None, error=None, group_chat=None):
        self.member = member
        self.error = error
        self.group_chat = group_chat or SimpleNamespace(
            username=None, invite_link=None
        )
        self.membership_checks = []
        self.replies = []
        self.reply_markups = []
        self.callback_answers = []
        self.sent = []

    def get_chat_member(self, group_id, user_id):
        self.membership_checks.append((group_id, user_id))
        if self.error:
            raise self.error
        return self.member

    def get_chat(self, group_id):
        assert group_id == -100123
        return self.group_chat

    def reply_to(self, message, text, reply_markup=None):
        self.replies.append((message, text))
        self.reply_markups.append(reply_markup)

    def answer_callback_query(self, callback_query_id, **kwargs):
        self.callback_answers.append((callback_query_id, kwargs))

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


def test_group_member_statuses_are_allowed():
    for status in ("creator", "administrator", "member"):
        assert is_group_member(SimpleNamespace(status=status))


def test_restricted_user_is_allowed_only_while_still_a_member():
    assert is_group_member(SimpleNamespace(status="restricted", is_member=True))
    assert not is_group_member(SimpleNamespace(status="restricted", is_member=False))


def test_users_who_left_or_were_kicked_are_denied():
    assert not is_group_member(SimpleNamespace(status="left"))
    assert not is_group_member(SimpleNamespace(status="kicked"))


def test_middleware_allows_a_group_member():
    bot = FakeBot(SimpleNamespace(status="member"))
    message = make_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB(-100123)).pre_process(
        message, {}
    )

    assert result is None
    assert bot.membership_checks == [(-100123, 42)]
    assert bot.replies == []


def test_middleware_denies_a_non_member():
    bot = FakeBot(SimpleNamespace(status="left"))
    message = make_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB(-100123)).pre_process(
        message, {}
    )

    assert isinstance(result, CancelUpdate)
    assert bot.replies == [(message, ACCESS_DENIED_MESSAGE)]


def test_middleware_denies_callback_with_an_alert():
    bot = FakeBot(SimpleNamespace(status="left"))
    message = make_message()
    callback_query = CallbackQuery(
        "callback-1", message.from_user, "home", "", None, message
    )

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB(-100123)).pre_process(
        callback_query, {}
    )

    assert isinstance(result, CancelUpdate)
    assert bot.callback_answers == [
        (
            "callback-1",
            {"text": ACCESS_DENIED_ALERT_MESSAGE, "show_alert": True},
        )
    ]
    assert bot.sent == [(42, ACCESS_DENIED_MESSAGE, None)]


def test_access_denial_links_to_public_group():
    bot = FakeBot(
        SimpleNamespace(status="left"),
        group_chat=SimpleNamespace(username="ShadowAl", invite_link=None),
    )
    message = make_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB(-100123)).pre_process(
        message, {}
    )

    assert isinstance(result, CancelUpdate)
    button = bot.reply_markups[0].keyboard[0][0]
    assert button.text == "👥 Открыть группу"
    assert button.url == "https://t.me/ShadowAl"


def test_access_messages_explain_next_step_and_support_contact():
    assert "Forge Master" in ACCESS_DENIED_MESSAGE
    assert "ShadowAl" in ACCESS_DENIED_MESSAGE
    assert "@AntonPleshakov" in ACCESS_DENIED_MESSAGE
    assert "через несколько минут" in ACCESS_CHECK_FAILED_MESSAGE
    assert "@AntonPleshakov" in ACCESS_GROUP_NOT_REGISTERED_MESSAGE


def test_middleware_fails_closed_when_membership_check_fails():
    bot = FakeBot(error=ConnectionError("Telegram is unavailable"))
    message = make_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB(-100123)).pre_process(
        message, {}
    )

    assert isinstance(result, CancelUpdate)
    assert bot.replies == [(message, ACCESS_CHECK_FAILED_MESSAGE)]


def test_middleware_denies_access_until_group_is_registered():
    bot = FakeBot()
    message = make_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB()).pre_process(message, {})

    assert isinstance(result, CancelUpdate)
    assert bot.membership_checks == []
    assert bot.replies == [(message, ACCESS_GROUP_NOT_REGISTERED_MESSAGE)]


def test_middleware_allows_group_registration_command_before_registration():
    bot = FakeBot()
    message = make_message(chat_type="supergroup", text="/register_group")

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB()).pre_process(message, {})

    assert result is None
    assert bot.membership_checks == []
    assert bot.replies == []


class FakeRegistrationBot:
    def __init__(self, bot_status="administrator"):
        self.bot_status = bot_status
        self.replies = []

    def get_me(self):
        return SimpleNamespace(id=999)

    def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.bot_status)

    def reply_to(self, message, text):
        self.replies.append((message, text))


def test_admin_can_register_group(monkeypatch):
    import tg.group_registration as registration

    database = FakeAccessGroupDB()
    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(is_admin=lambda user_id: True),
    )
    monkeypatch.setattr(registration, "get_access_group_db", lambda: database)
    bot = FakeRegistrationBot()
    message = make_message(chat_type="supergroup", text="/register_group")

    register_access_group(message, bot)

    assert database.get_group_id() == message.chat.id
    assert bot.replies == [(message, REGISTRATION_SUCCESS_MESSAGE)]


def test_non_admin_cannot_register_group(monkeypatch):
    import tg.group_registration as registration

    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(is_admin=lambda user_id: False),
    )
    bot = FakeRegistrationBot()
    message = make_message(chat_type="group", text="/register_group")

    register_access_group(message, bot)

    assert bot.replies == [(message, NOT_ADMIN_MESSAGE)]


def test_bot_must_be_group_admin_before_registration(monkeypatch):
    import tg.group_registration as registration

    database = FakeAccessGroupDB()
    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(is_admin=lambda user_id: True),
    )
    monkeypatch.setattr(registration, "get_access_group_db", lambda: database)
    bot = FakeRegistrationBot(bot_status="member")
    message = make_message(chat_type="group", text="/register_group")

    register_access_group(message, bot)

    assert database.get_group_id() is None
    assert bot.replies == [(message, BOT_NOT_ADMIN_MESSAGE)]
