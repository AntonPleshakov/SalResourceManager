from types import SimpleNamespace
from unittest.mock import Mock

from telebot import TeleBot

from tg.debug_bot import DebugTeleBot


class FakeGroups:
    def get_group(self, group_id):
        if group_id == -100123:
            return SimpleNamespace(group_id=group_id, title="Local clan")
        return None


class FakeAdmins:
    def is_clan_admin(self, user_id, group_id):
        return user_id == 42 and group_id == -100123


def make_bot():
    bot = DebugTeleBot("123:test-token")
    bot.configure_fake_clan_data(FakeGroups(), FakeAdmins())
    return bot


def test_known_clan_chat_comes_from_local_database():
    chat = make_bot().get_chat(-100123)

    assert chat.id == -100123
    assert chat.type == "supergroup"
    assert chat.title == "Local clan"


def test_local_acl_controls_fake_administrator_status():
    bot = make_bot()

    assert bot.get_chat_member(-100123, 42).status == "administrator"
    assert bot.get_chat_member(-100123, 77).status == "member"
    assert bot.get_chat_member(-100123, 123).status == "administrator"


def test_unknown_chat_uses_real_telegram_lookups(monkeypatch):
    expected_chat = object()
    expected_member = object()
    get_chat = Mock(return_value=expected_chat)
    get_chat_member = Mock(return_value=expected_member)
    monkeypatch.setattr(TeleBot, "get_chat", get_chat)
    monkeypatch.setattr(TeleBot, "get_chat_member", get_chat_member)
    bot = make_bot()

    assert bot.get_chat(-999) is expected_chat
    assert bot.get_chat_member(-999, 77) is expected_member
    get_chat.assert_called_once_with(-999)
    get_chat_member.assert_called_once_with(-999, 77)
