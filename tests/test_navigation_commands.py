from pathlib import Path
from types import SimpleNamespace

from telebot.types import (
    BotCommandScopeAllPrivateChats,
    Chat,
    Message,
    ReplyKeyboardRemove,
    User,
)

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

import tg.manager as manager
import tg.navigation as navigation
from tg.manager import (
    VISIBLE_COMMANDS,
    cancel_command,
    configure_commands,
    open_menu_command,
    start_command,
)


def make_message(text: str) -> Message:
    user = User(42, False, "Tester", username="tester")
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
    def __init__(self, state=None):
        self.state = state
        self.deleted_states = []
        self.sent = []
        self.replies = []
        self.commands = []

    def get_state(self, user_id, chat_id=None):
        return self.state

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)
        self.state = None

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def reply_to(self, message, text):
        self.replies.append((message, text))

    def set_my_commands(self, commands, scope):
        self.commands.append((commands, scope))


def prepare_home(monkeypatch):
    monkeypatch.setattr("tg.navigation.show_new_user_welcome", lambda *_: False)
    monkeypatch.setattr(
        "tg.navigation.show_unseen_releases",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("direct menu navigation must skip release notes")
        ),
    )
    monkeypatch.setattr(
        "tg.navigation.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {"is_admin": lambda self, user_id: False},
        )(),
    )
    monkeypatch.setattr(
        "tg.navigation.get_user_data_db",
        lambda: SimpleNamespace(
            get_accounts=lambda _user_id: [
                SimpleNamespace(tag="Лидер", is_active=True)
            ]
        ),
    )


def test_menu_command_cancels_active_state_and_opens_home(monkeypatch):
    prepare_home(monkeypatch)
    bot = FakeBot(state="editing")

    open_menu_command(make_message("/menu"), bot)

    assert bot.deleted_states == [42]
    assert bot.sent[0][1] == "Текущее действие отменено."
    assert isinstance(bot.sent[0][2], ReplyKeyboardRemove)
    assert bot.sent[1][1] == (
        "Игровой аккаунт: <b>Лидер</b>\n\nВыберите раздел."
    )


def test_start_command_checks_unseen_releases(monkeypatch):
    release_checks = []
    monkeypatch.setattr("tg.navigation.show_new_user_welcome", lambda *_: False)
    monkeypatch.setattr(
        "tg.navigation.show_unseen_releases",
        lambda *_: release_checks.append(True) or True,
    )
    bot = FakeBot()

    start_command(make_message("/start"), bot)

    assert release_checks == [True]
    assert bot.sent == []


def test_cancel_without_active_state_is_neutral(monkeypatch):
    prepare_home(monkeypatch)
    bot = FakeBot()
    message = make_message("/cancel")

    cancel_command(message, bot)

    assert bot.deleted_states == []
    assert bot.sent == []
    assert bot.replies == [(message, "Сейчас нет активного действия.")]


def test_cancel_with_active_state_cancels_and_opens_home(monkeypatch):
    prepare_home(monkeypatch)
    bot = FakeBot(state="editing")

    cancel_command(make_message("/cancel"), bot)

    assert bot.deleted_states == [42]
    assert isinstance(bot.sent[0][2], ReplyKeyboardRemove)
    assert bot.sent[1][1] == (
        "Игровой аккаунт: <b>Лидер</b>\n\nВыберите раздел."
    )


def test_home_shows_account_count_only_for_multiple_accounts(monkeypatch):
    prepare_home(monkeypatch)
    monkeypatch.setattr(
        "tg.navigation.get_user_data_db",
        lambda: SimpleNamespace(
            get_accounts=lambda _user_id: [
                SimpleNamespace(tag="Main & Hero", is_active=True),
                SimpleNamespace(tag="Alt", is_active=False),
            ]
        ),
    )
    bot = FakeBot()

    navigation.home(make_message("/menu"), bot)

    assert bot.sent[0][1] == (
        "Игровой аккаунт: <b>Main &amp; Hero</b>\n"
        "Всего аккаунтов: 2\n\n"
        "Выберите раздел."
    )


def test_only_start_and_menu_are_published():
    bot = FakeBot()

    configure_commands(bot)

    commands, scope = bot.commands[0]
    assert commands == list(VISIBLE_COMMANDS)
    assert [command.command for command in commands] == ["start", "menu"]
    assert isinstance(scope, BotCommandScopeAllPrivateChats)


def test_onboarding_marks_current_release_without_showing_release_notes(
    monkeypatch,
):
    marked = []
    monkeypatch.setattr(
        "tg.navigation.show_new_user_welcome", lambda *_: True
    )
    monkeypatch.setattr(
        "tg.navigation.mark_current_release_seen",
        lambda message: marked.append(message.from_user.id),
    )
    monkeypatch.setattr(
        "tg.navigation.show_unseen_releases",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    bot = FakeBot()
    navigation.home(make_message("/start"), bot)

    assert marked == [42]
    assert bot.sent == []


def test_recovery_commands_are_registered_before_scenario_handlers(monkeypatch):
    for module in (
        manager.group_registration,
        manager.user_data,
        manager.war,
        manager.releases,
        manager.admins,
    ):
        monkeypatch.setattr(module, "register_handlers", lambda bot: None)

    class RegistrationBot:
        def __init__(self):
            self.message_handlers = []

        def register_message_handler(self, handler, **kwargs):
            self.message_handlers.append((handler, kwargs))

        def register_callback_query_handler(self, handler, **kwargs):
            pass

    bot = RegistrationBot()

    manager.register_handlers(bot)

    assert bot.message_handlers[0][0] is start_command
    assert bot.message_handlers[0][1]["commands"] == ["start"]
    assert bot.message_handlers[1][0] is open_menu_command
    assert bot.message_handlers[1][1]["commands"] == ["menu"]
    assert bot.message_handlers[2][0] is cancel_command
    assert bot.message_handlers[2][1]["commands"] == ["cancel"]
