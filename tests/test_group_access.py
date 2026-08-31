from pathlib import Path
from types import SimpleNamespace

from prometheus_client import CollectorRegistry
from telebot.handler_backends import CancelUpdate
from telebot.types import CallbackQuery, Chat, ChatShared, Message, User

from config.config import reset_config
from db.access_group import AccessGroup, AccessGroupDB
from db.admins import Admin, AdminsDB
from db.database import Database

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
    GROUP_REGISTRATION_REQUEST_ID,
    GROUP_SELECTION_MESSAGE,
    GroupRegistrationStates,
    NOT_ADMIN_MESSAGE,
    REGISTRATION_SUCCESS_MESSAGE,
    USER_NOT_GROUP_ADMIN_MESSAGE,
    register_current_group,
    register_selected_group,
    request_group_registration,
)
from tg.metrics import ApplicationMetrics


def make_message(user_id=42, chat_type="private", text="hello"):
    user = User(user_id, False, "Tester", username="tester")
    chat_id = user_id if chat_type == "private" else -100123
    chat = Chat(chat_id, chat_type, title="Test group")
    return Message(1, user, 0, chat, "text", {"text": text}, None)


def make_shared_group_message(
    user_id=42, group_id=-100123, request_id=GROUP_REGISTRATION_REQUEST_ID
):
    message = make_message(user_id=user_id)
    message.content_type = "chat_shared"
    message.chat_shared = ChatShared(request_id, group_id, title="Test group")
    return message


def make_callback(data="admins/register_group"):
    message = make_message()
    return CallbackQuery("callback-1", message.from_user, data, "", None, message)


class FakeAccessGroupDB:
    def __init__(self, group_id=None):
        self.group_id = group_id

    def get_groups(self):
        return (
            []
            if self.group_id is None
            else [AccessGroup(self.group_id, "Test group")]
        )

    def add_group(self, group_id, title):
        self.group_id = group_id
        return AccessGroup(group_id, title)


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


def test_middleware_allows_member_of_any_registered_clan():
    groups = SimpleNamespace(
        get_groups=lambda: [
            AccessGroup(-100001, "Alpha"),
            AccessGroup(-100002, "Beta"),
        ]
    )

    class MultiClanBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            self.membership_checks.append((group_id, user_id))
            return SimpleNamespace(
                status="member" if group_id == -100002 else "left"
            )

    bot = MultiClanBot()

    result = GroupAccessMiddleware(bot, groups).pre_process(make_message(), {})

    assert result is None
    assert bot.membership_checks == [(-100001, 42), (-100002, 42)]


def test_access_decisions_are_recorded() -> None:
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)

    GroupAccessMiddleware(
        FakeBot(SimpleNamespace(status="member")),
        FakeAccessGroupDB(-100123),
        metrics,
    ).pre_process(make_message(), {})
    GroupAccessMiddleware(
        FakeBot(SimpleNamespace(status="left")),
        FakeAccessGroupDB(-100123),
        metrics,
    ).pre_process(make_message(), {})
    GroupAccessMiddleware(
        FakeBot(error=ConnectionError("unavailable")),
        FakeAccessGroupDB(-100123),
        metrics,
    ).pre_process(make_message(), {})
    GroupAccessMiddleware(FakeBot(), FakeAccessGroupDB(), metrics).pre_process(
        make_message(), {}
    )
    GroupAccessMiddleware(FakeBot(), FakeAccessGroupDB(), metrics).pre_process(
        make_message(chat_type="supergroup", text="/register_group"), {}
    )
    GroupAccessMiddleware(FakeBot(), FakeAccessGroupDB(), metrics).pre_process(
        make_message(chat_type="supergroup", text="hello"), {}
    )

    for result in (
        "allowed",
        "denied",
        "error",
        "unconfigured",
        "bypassed",
        "ignored",
    ):
        assert registry.get_sample_value(
            "srm_access_checks_total", {"result": result}
        ) == 1


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
    assert button.text == "👥 Test group"
    assert button.url == "https://t.me/ShadowAl"


def test_access_messages_explain_next_step_and_support_contact():
    assert "Forge Master" in ACCESS_DENIED_MESSAGE
    assert "зарегистрированных кланов" in ACCESS_DENIED_MESSAGE
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


def test_middleware_ignores_other_group_updates_immediately():
    class UnexpectedDB:
        def get_groups(self):
            raise AssertionError("Group updates must not query registered clans")

    bot = FakeBot(error=AssertionError("Membership must not be checked"))
    message = make_message(chat_type="supergroup", text="hello")
    callback = CallbackQuery(
        "callback-1", message.from_user, "home", "", None, message
    )

    for update in (message, callback):
        result = GroupAccessMiddleware(bot, UnexpectedDB()).pre_process(update, {})
        assert isinstance(result, CancelUpdate)

    assert bot.membership_checks == []
    assert bot.replies == []
    assert bot.callback_answers == []


def test_middleware_does_not_treat_private_text_as_registration_command():
    bot = FakeBot()
    message = make_message(chat_type="private", text="/register_group")

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB()).pre_process(message, {})

    assert isinstance(result, CancelUpdate)
    assert bot.replies == [(message, ACCESS_GROUP_NOT_REGISTERED_MESSAGE)]


def test_middleware_does_not_bypass_shared_group_before_registration():
    bot = FakeBot()
    message = make_shared_group_message()

    result = GroupAccessMiddleware(bot, FakeAccessGroupDB()).pre_process(message, {})

    assert isinstance(result, CancelUpdate)
    assert bot.membership_checks == []
    assert bot.replies == [(message, ACCESS_GROUP_NOT_REGISTERED_MESSAGE)]


class FakeRegistrationBot:
    def __init__(
        self,
        bot_status="administrator",
        user_status="administrator",
        group_type="supergroup",
    ):
        self.bot_status = bot_status
        self.user_status = user_status
        self.group_type = group_type
        self.replies = []
        self.sent = []
        self.states = []
        self.deleted_states = []

    def get_me(self):
        return SimpleNamespace(id=999)

    def get_chat_member(self, chat_id, user_id):
        status = self.bot_status if user_id == 999 else self.user_status
        return SimpleNamespace(status=status)

    def get_chat(self, chat_id):
        return SimpleNamespace(id=chat_id, type=self.group_type, title="Test group")

    def reply_to(self, message, text, reply_markup=None):
        self.replies.append((message, text, reply_markup))

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)


def test_bot_admin_gets_picker_without_telegram_admin_requirement(monkeypatch):
    import tg.group_registration as registration

    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(
            is_admin=lambda user_id: True,
            add_admin=lambda admin, group_id: None,
            select_group=lambda user_id, group_id: None,
        ),
    )
    bot = FakeRegistrationBot()
    callback = make_callback()

    request_group_registration(callback, bot)

    assert bot.sent[0][:2] == (callback.message.chat.id, GROUP_SELECTION_MESSAGE)
    button = bot.sent[0][2].keyboard[0][0]
    assert button["request_chat"]["chat_is_channel"] is False
    assert button["request_chat"]["bot_is_member"] is True
    assert "user_administrator_rights" not in button["request_chat"]
    assert "bot_administrator_rights" not in button["request_chat"]
    assert bot.states == [(42, GroupRegistrationStates.select_group)]


def test_bot_admin_can_register_selected_group_without_telegram_admin_rights(
    monkeypatch,
):
    import tg.group_registration as registration

    database = FakeAccessGroupDB()
    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(
            is_admin=lambda user_id: True,
            add_admin=lambda admin, group_id: None,
            select_group=lambda user_id, group_id: None,
        ),
    )
    monkeypatch.setattr(registration, "get_access_group_db", lambda: database)
    bot = FakeRegistrationBot(user_status="member")
    message = make_shared_group_message()

    register_selected_group(message, bot)

    assert database.get_groups() == [
        AccessGroup(message.chat_shared.chat_id, "Test group")
    ]
    assert bot.replies[0][0:2] == (
        message,
        REGISTRATION_SUCCESS_MESSAGE.format(title="Test group"),
    )
    assert bot.deleted_states == [42]


def test_selected_group_handler_requires_registration_state():
    import tg.group_registration as registration

    class FakeHandlersBot:
        def __init__(self):
            self.message_handlers = []

        def register_message_handler(self, callback, **kwargs):
            self.message_handlers.append((callback, kwargs))

        def register_callback_query_handler(self, callback, **kwargs):
            pass

    bot = FakeHandlersBot()

    registration.register_handlers(bot)

    handler = next(
        kwargs
        for callback, kwargs in bot.message_handlers
        if callback is register_selected_group
    )
    assert handler["content_types"] == ["chat_shared"]
    assert handler["chat_types"] == ["private"]
    assert handler["state"] is GroupRegistrationStates.select_group


def test_registration_adds_clans_and_grants_requester_scoped_admin_rights(
    tmp_path, monkeypatch
):
    import tg.group_registration as registration

    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    admins = AdminsDB(connection)
    admins.add_admin(Admin("tester", 42))
    monkeypatch.setattr(registration, "get_admins_db", lambda: admins)
    monkeypatch.setattr(registration, "get_access_group_db", lambda: groups)
    bot = FakeRegistrationBot()

    register_selected_group(make_shared_group_message(group_id=-100001), bot)
    register_selected_group(make_shared_group_message(group_id=-100002), bot)

    assert [group.group_id for group in groups.get_groups()] == [
        -100002,
        -100001,
    ]
    assert {group.group_id for group in admins.get_clans(42)} == {
        -100002,
        -100001,
    }
    assert admins.get_active_group(42).group_id == -100002
    connection.close()


def test_non_admin_cannot_register_group(monkeypatch):
    import tg.group_registration as registration

    monkeypatch.setattr(
        registration,
        "get_admins_db",
        lambda: SimpleNamespace(is_admin=lambda user_id: False),
    )
    bot = FakeRegistrationBot()
    message = make_shared_group_message()

    register_selected_group(message, bot)

    assert bot.replies[0][0:2] == (message, NOT_ADMIN_MESSAGE)


def test_telegram_group_admin_can_register_without_existing_bot_rights(
    tmp_path, monkeypatch
):
    import tg.group_registration as registration

    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    admins = AdminsDB(connection)
    monkeypatch.setattr(registration, "get_admins_db", lambda: admins)
    monkeypatch.setattr(registration, "get_access_group_db", lambda: groups)
    bot = FakeRegistrationBot(user_status="administrator")
    message = make_message(chat_type="supergroup", text="/register_group")

    register_current_group(message, bot)

    assert groups.get_group(message.chat.id).title == "Test group"
    assert admins.is_admin(42, message.chat.id)
    assert admins.get_active_group(42).group_id == message.chat.id
    assert bot.replies[0][0:2] == (
        message,
        REGISTRATION_SUCCESS_MESSAGE.format(title="Test group"),
    )
    connection.close()


def test_group_member_cannot_register_current_group(monkeypatch):
    import tg.group_registration as registration

    database = FakeAccessGroupDB()
    monkeypatch.setattr(registration, "get_access_group_db", lambda: database)
    bot = FakeRegistrationBot(user_status="member")
    message = make_message(chat_type="supergroup", text="/register_group")

    register_current_group(message, bot)

    assert database.get_groups() == []
    assert bot.replies[0][0:2] == (message, USER_NOT_GROUP_ADMIN_MESSAGE)


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
    message = make_shared_group_message()

    register_selected_group(message, bot)

    assert database.get_groups() == []
    assert bot.replies[0][0:2] == (message, BOT_NOT_ADMIN_MESSAGE)
