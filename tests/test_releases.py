from datetime import date
from pathlib import Path

import pytest
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.releases import CURRENT_VERSION, RELEASES, Release, unseen_releases
from tg.releases import format_release_notes, show_release_notes, show_unseen_releases


def make_callback(user_id: int = 42, data: str = "releases") -> CallbackQuery:
    user = User(user_id, False, "Tester", username="tester")
    chat = Chat(user_id, "private")
    message = Message(1, user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


class FakeReleaseViewsDB:
    def __init__(self, version=None, username=""):
        self.version = version
        self.username = username
        self.marked = []
        self.updated_usernames = []

    def get_last_seen_version(self, user_id):
        return self.version

    def update_username(self, user_id, username):
        self.updated_usernames.append((user_id, username))
        self.username = username

    def mark_seen(self, user_id, username, version):
        self.marked.append((user_id, username, version))
        self.username = username
        self.version = version


class FakeBot:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []
        self.edited = []

    def send_message(self, chat_id, text, reply_markup=None):
        if self.fail:
            raise RuntimeError("Telegram unavailable")
        self.sent.append((chat_id, text, reply_markup))

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        if self.fail:
            raise RuntimeError("Telegram unavailable")
        self.edited.append((text, chat_id, message_id, reply_markup))


def callback_data(markup):
    return [button.callback_data for row in markup.keyboard for button in row]


def test_new_user_sees_up_to_five_current_releases(monkeypatch):
    releases = tuple(
        Release(str(index) + ".0.0", date(2026, 8, index), ("Изменение",))
        for index in range(1, 7)
    )
    monkeypatch.setattr("resources.releases.RELEASES", releases)

    assert unseen_releases(None) == releases[-5:]


def test_current_user_has_no_unseen_releases():
    assert unseen_releases(CURRENT_VERSION) == ()


def test_user_sees_every_release_published_after_last_seen_version():
    assert [release.version for release in unseen_releases("1.0.0")] == [
        "1.0.1",
        "1.1.0",
        "1.2.0",
        "1.3.0",
        "1.4.0",
        "1.5.0",
    ]


def test_latest_release_is_version_1_5_0():
    assert CURRENT_VERSION == "1.5.0"
    assert [release.version for release in unseen_releases("1.4.0")] == ["1.5.0"]


def test_release_notes_contain_version_changes_and_date():
    text = format_release_notes(RELEASES[-1:])

    assert f"Версия {CURRENT_VERSION}" in text
    assert RELEASES[-1].released_on.strftime("%d.%m.%Y") in text
    assert RELEASES[-1].changes[0] in text


def test_unseen_release_is_marked_only_after_successful_display(monkeypatch):
    database = FakeReleaseViewsDB()
    monkeypatch.setattr("tg.releases.get_release_views_db", lambda: database)
    callback = make_callback()

    assert show_unseen_releases(callback, FakeBot()) is True
    assert database.marked == [(42, "tester", CURRENT_VERSION)]

    database.marked.clear()
    database.version = None
    with pytest.raises(RuntimeError, match="Telegram unavailable"):
        show_unseen_releases(callback, FakeBot(fail=True))
    assert database.marked == []


def test_username_is_updated_even_when_there_are_no_unseen_releases(monkeypatch):
    database = FakeReleaseViewsDB(CURRENT_VERSION, "old_username")
    monkeypatch.setattr("tg.releases.get_release_views_db", lambda: database)

    assert show_unseen_releases(make_callback(), FakeBot()) is False
    assert database.updated_usernames == [(42, "tester")]


def test_release_button_shows_current_release_and_returns_home(monkeypatch):
    database = FakeReleaseViewsDB(CURRENT_VERSION)
    monkeypatch.setattr("tg.releases.get_release_views_db", lambda: database)
    bot = FakeBot()

    show_release_notes(make_callback(), bot)

    assert f"Версия {CURRENT_VERSION}" in bot.edited[0][0]
    assert callback_data(bot.edited[0][3]) == ["home"]
