from pathlib import Path
from types import SimpleNamespace

from telebot.handler_backends import CancelUpdate
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.access_group import ACCESS_GROUP_ID_KEY, AccessGroupDB
from tg.access import (
    ACCESS_CHECK_FAILED_MESSAGE,
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
    def __init__(self, member=None, error=None):
        self.member = member
        self.error = error
        self.membership_checks = []
        self.replies = []
        self.callback_answers = []

    def get_chat_member(self, group_id, user_id):
        self.membership_checks.append((group_id, user_id))
        if self.error:
            raise self.error
        return self.member

    def reply_to(self, message, text):
        self.replies.append((message, text))

    def answer_callback_query(self, callback_query_id, **kwargs):
        self.callback_answers.append((callback_query_id, kwargs))


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
            {"text": ACCESS_DENIED_MESSAGE, "show_alert": True},
        )
    ]


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


class FakeWorksheetManager:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def fetch(self):
        pass

    def get_all_values(self):
        return self.rows

    def update_values(self, rows):
        self.rows = rows


def test_access_group_database_loads_and_updates_group_id():
    manager = FakeWorksheetManager([[ACCESS_GROUP_ID_KEY, "-100111"]])
    database = AccessGroupDB(manager)

    assert database.get_group_id() == -100111

    database.set_group_id(-100222)

    assert database.get_group_id() == -100222
    assert manager.rows == [[ACCESS_GROUP_ID_KEY, "-100222"]]


def test_access_group_database_creates_settings_worksheet(monkeypatch):
    import db.access_group as access_group

    manager = FakeWorksheetManager()

    class FakeSpreadsheet:
        def __init__(self):
            self.added_worksheets = []

        def is_worksheet_exist(self, worksheet_name):
            return False

        def add_worksheet(self, worksheet_name):
            self.added_worksheets.append(worksheet_name)
            return manager

    spreadsheet = FakeSpreadsheet()
    monkeypatch.setattr(
        access_group,
        "GSheetsManager",
        lambda: SimpleNamespace(open=lambda spreadsheet_id: spreadsheet),
    )

    database = AccessGroupDB()

    assert database.get_group_id() is None
    assert spreadsheet.added_worksheets == ["Settings"]


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
