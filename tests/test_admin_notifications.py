from pathlib import Path

import pytest

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.admins.notifications import (
    MAX_CUSTOM_TEXT_LENGTH,
    STANDARD_NOTIFICATION_TEXT,
    BroadcastResult,
    build_custom_notification_messages,
    send_custom_notification,
    send_custom_private_notification,
    send_standard_notification,
)


class FakeUserDataDB:
    def __init__(self, users):
        self._users = users

    def get_users(self):
        return self._users


def test_standard_notification_is_sent_to_every_user(monkeypatch):
    users = [UserData(user_id=1), UserData(user_id=2)]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db", lambda: FakeUserDataDB(users)
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, reply_markup):
            self.calls.append((user_id, text, reply_markup))
            if user_id == 1:
                raise RuntimeError("blocked")

    bot = FakeBot()

    result = send_standard_notification(bot)

    assert result == BroadcastResult(sent=1, failed=1)
    assert [call[0] for call in bot.calls] == [1, 2]
    assert all(call[1] == STANDARD_NOTIFICATION_TEXT for call in bot.calls)
    assert len(bot.calls[0][2].keyboard) == 2


def test_custom_notification_escapes_text_and_mentions_every_user():
    users = [
        UserData(user_id=1, username="one"),
        UserData(user_id=2, username="<Two>"),
    ]

    messages = build_custom_notification_messages(
        "Проверка <важно>", "Admin & owner", users
    )

    combined = "\n".join(messages)
    assert "Проверка &lt;важно&gt;" in combined
    assert "Admin &amp; owner" in combined
    assert '<a href="tg://user?id=1">one</a>' in combined
    assert '<a href="tg://user?id=2">&lt;Two&gt;</a>' in combined


def test_custom_notification_splits_long_mention_list():
    users = [
        UserData(user_id=index, username="user" + "x" * 60)
        for index in range(1, 80)
    ]

    messages = build_custom_notification_messages("Текст", "Admin", users)

    assert len(messages) > 1
    assert all(len(message) <= 4_096 for message in messages)
    assert sum(message.count("tg://user?id=") for message in messages) == len(users)


def test_custom_notification_rejects_empty_or_too_long_text():
    with pytest.raises(ValueError):
        build_custom_notification_messages("  ", "Admin", [])
    with pytest.raises(ValueError):
        build_custom_notification_messages(
            "x" * (MAX_CUSTOM_TEXT_LENGTH + 1), "Admin", []
        )


def test_custom_notification_is_sent_to_access_group_with_sound(monkeypatch):
    users = [UserData(user_id=1, username="one")]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db", lambda: FakeUserDataDB(users)
    )

    class FakeAccessGroupDB:
        def get_group_id(self):
            return -100123

    monkeypatch.setattr(
        "tg.admins.notifications.get_access_group_db",
        lambda: FakeAccessGroupDB(),
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, group_id, text, disable_notification):
            self.calls.append((group_id, text, disable_notification))

    bot = FakeBot()

    result = send_custom_notification(bot, "Важный текст", "Admin")

    assert result == BroadcastResult(sent=1, failed=0)
    assert bot.calls[0][0] == -100123
    assert bot.calls[0][2] is False
    assert "tg://user?id=1" in bot.calls[0][1]


def test_custom_private_notification_is_sent_to_every_user(monkeypatch):
    users = [
        UserData(user_id=1, username="one"),
        UserData(user_id=2, username="two"),
    ]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db", lambda: FakeUserDataDB(users)
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, disable_notification):
            self.calls.append((user_id, text, disable_notification))
            if user_id == 1:
                raise RuntimeError("blocked")

    bot = FakeBot()

    result = send_custom_private_notification(
        bot, "Личный <текст>", "Admin & owner"
    )

    assert result == BroadcastResult(sent=1, failed=1)
    assert [call[0] for call in bot.calls] == [1, 2]
    assert all(call[2] is False for call in bot.calls)
    assert "Личный &lt;текст&gt;" in bot.calls[0][1]
    assert "Admin &amp; owner" in bot.calls[0][1]
    assert "tg://user?id=" not in bot.calls[0][1]
