import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from telebot.types import CallbackQuery, Chat, Message, User

import db.initializer
import tg.manager
from db.access_group import AccessGroup
from tg.handlers import (
    ClanAdminContext,
    ClanFromCallback,
    ClanFromState,
    HandlerRegistry,
)
from tg.observability.handlers import instrument_registered_handlers


PROJECT_ROOT = Path(__file__).parents[1]
HANDLER_REGISTRY_FILE = PROJECT_ROOT / "tg" / "handlers.py"


class FakeBot:
    def __init__(self):
        self.callback_handlers = []
        self.message_handlers = []
        self.callback_answers = []
        self.deleted_states = []

    def register_callback_query_handler(self, handler, **filters):
        self.callback_handlers.append((handler, filters))

    def register_message_handler(self, handler, **filters):
        self.message_handlers.append((handler, filters))

    def answer_callback_query(self, callback_id, text, show_alert=False):
        self.callback_answers.append((callback_id, text, show_alert))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)


class InstrumentableBot(FakeBot):
    @property
    def callback_query_handlers(self):
        return self.callback_handlers

    def register_callback_query_handler(self, handler, **filters):
        self.callback_handlers.append({"function": handler, **filters})

    def register_message_handler(self, handler, **filters):
        self.message_handlers.append({"function": handler, **filters})


class StatefulBot(FakeBot):
    def __init__(self, data):
        super().__init__()
        self.data = data

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def get_chat_member(self, group_id, user_id):
        return SimpleNamespace(status="member")


class AllowClan:
    def authorize(self, context):
        return ClanAdminContext(
            **context.__dict__,
            group=AccessGroup(-100123, "Test clan"),
        )


class DenyClan:
    def authorize(self, context):
        raise ValueError("Нет доступа к клану")


def make_callback(data: str = "admins/action") -> CallbackQuery:
    user = User(42, False, "Tester", username="tester")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def _raw_registration_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr
        in {"register_callback_query_handler", "register_message_handler"}
    ]


def _private_admin_callbacks(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "private_callback"
        ):
            continue
        button = next(
            (
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "button"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ),
            "",
        )
        if button == "admins" or button.startswith("admins/"):
            violations.append(node.lineno)
    return violations


def test_private_callback_profile_supplies_safe_defaults():
    bot = FakeBot()
    handler = lambda update, bot: None

    HandlerRegistry(bot).private_callback(handler, button="resources")

    registered, filters = bot.callback_handlers[0]
    assert registered is handler
    assert filters["button"] == "resources"
    assert filters["is_private"] is True
    assert filters["pass_bot"] is True
    assert filters["func"](object()) is True


def test_clan_admin_profile_injects_authorized_context():
    bot = FakeBot()
    received = []

    def handler(context):
        received.append(context)

    HandlerRegistry(bot).clan_admin_callback(
        handler,
        button="admins/action",
        clan=AllowClan(),
    )
    registered, filters = bot.callback_handlers[0]

    registered(make_callback(), bot)

    assert filters["is_admin"] is True
    assert received[0].user_id == 42
    assert received[0].username == "tester"
    assert received[0].group.group_id == -100123


def test_stateful_admin_profile_fails_closed_and_clears_state():
    bot = FakeBot()
    called = []
    HandlerRegistry(bot).clan_admin_callback(
        lambda context: called.append(context),
        button="approved",
        state="confirmation",
        clan=DenyClan(),
    )
    registered = bot.callback_handlers[0][0]

    registered(make_callback("approved"), bot)

    assert called == []
    assert bot.deleted_states == [42]
    assert bot.callback_answers == [
        ("callback-1", "Нет доступа к клану", True)
    ]


def test_context_injection_is_compatible_with_handler_instrumentation():
    bot = InstrumentableBot()
    received = []

    def handler(context):
        received.append(context)

    HandlerRegistry(bot).clan_admin_callback(
        handler,
        button="admins/action",
        clan=AllowClan(),
    )
    instrument_registered_handlers(bot)

    bot.callback_handlers[0]["function"](make_callback(), {}, bot)

    assert received[0].group.group_id == -100123


def test_clan_from_callback_authorizes_the_embedded_clan(monkeypatch):
    group = AccessGroup(-100999, "Callback clan")
    admins = SimpleNamespace(
        is_clan_admin=lambda user_id, group_id: group_id == group.group_id,
        get_clans=lambda user_id: [group],
    )
    monkeypatch.setattr(db.initializer, "get_admins_db", lambda: admins)
    bot = StatefulBot({})
    received = []

    def handler(context):
        received.append(context)

    HandlerRegistry(bot).clan_admin_callback(
        handler,
        button=r"admins/action/-?[0-9]+",
        clan=ClanFromCallback(),
    )
    registered = bot.callback_handlers[0][0]

    registered(make_callback("admins/action/-100999"), bot)

    assert received[0].group == group


def test_clan_from_state_denies_revoked_access_and_clears_state(monkeypatch):
    admins = SimpleNamespace(
        is_clan_admin=lambda user_id, group_id: False,
    )
    monkeypatch.setattr(db.initializer, "get_admins_db", lambda: admins)
    bot = StatefulBot({"admin_group_id": -100123})
    called = []

    def handler(context):
        called.append(context)

    HandlerRegistry(bot).clan_admin_callback(
        handler,
        button="approved",
        state="confirmation",
        clan=ClanFromState(),
    )
    registered = bot.callback_handlers[0][0]

    registered(make_callback("approved"), bot)

    assert called == []
    assert bot.deleted_states == [42]
    assert "Нет прав администратора" in bot.callback_answers[0][1]


def test_protected_profile_rejects_legacy_handler_signature():
    bot = FakeBot()

    def legacy_handler(update, bot):
        return None

    try:
        HandlerRegistry(bot).clan_admin_callback(
            legacy_handler,
            button="admins/action",
            clan=AllowClan(),
        )
    except TypeError as error:
        assert "exactly one 'context' argument" in str(error)
    else:
        raise AssertionError("Legacy protected handler was registered")


def test_application_registers_all_handlers_through_valid_profiles():
    bot = FakeBot()

    tg.manager.register_handlers(bot)

    assert len(bot.callback_handlers) > 30
    assert len(bot.message_handlers) > 5


def test_raw_telebot_registration_is_confined_to_handler_registry():
    violations = {
        str(path.relative_to(PROJECT_ROOT)): lines
        for path in [PROJECT_ROOT / "main.py", *(PROJECT_ROOT / "tg").rglob("*.py")]
        if path != HANDLER_REGISTRY_FILE
        and (lines := _raw_registration_calls(path))
    }

    assert violations == {}


def test_admin_routes_cannot_use_unprotected_private_callback_profile():
    violations = {
        str(path.relative_to(PROJECT_ROOT)): lines
        for path in (PROJECT_ROOT / "tg").rglob("*.py")
        if path != HANDLER_REGISTRY_FILE
        and (lines := _private_admin_callbacks(path))
    }

    assert violations == {}
