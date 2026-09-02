from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config
from db.access_group import AccessGroup

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.admins.notifications import (
    MAX_CUSTOM_TEXT_LENGTH,
    STANDARD_NOTIFICATION_TEXT,
    BroadcastResult,
    CustomNotificationAudience,
    build_standard_notification_plan,
    build_custom_notification_messages,
    confirm_standard_notification,
    receive_custom_notification_text,
    send_custom_notification,
    send_custom_group_notification_confirmed,
    send_custom_private_notification,
    send_custom_private_notification_confirmed,
    send_standard_notification,
    send_standard_notification_confirmed,
    select_custom_notification_audience,
)
from tg.admins.notification import filter_custom_notification_users


@pytest.fixture(autouse=True)
def allow_admin_access(monkeypatch):
    monkeypatch.setattr(
        "tg.admins.notifications.get_admins_db",
        lambda: SimpleNamespace(
            is_clan_admin=lambda user_id, group_id: True
        ),
    )


def make_callback(data: str = "admins/notifications/standard") -> CallbackQuery:
    user = User(42, False, "Admin", username="admin")
    message = Message(
        1,
        user,
        0,
        Chat(42, "private"),
        "text",
        {"text": "menu"},
        None,
    )
    return CallbackQuery("callback-1", user, data, "", None, message)


class FakeUserDataDB:
    def __init__(self, users):
        self._users = users

    def get_clan_users(self, clan_id):
        return self._users

    def get_clan_user_ids(self, clan_id):
        return []


class NotificationFlowBot:
    def __init__(self, data):
        self.data = data
        self.edited = []
        self.answers = []
        self.deleted_states = []
        self.states = []

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def edit_message_text(self, *args, **kwargs):
        self.edited.append((args, kwargs))

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)


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

    plan = build_standard_notification_plan(users, date(2026, 8, 3))
    result = send_standard_notification(bot, plan)

    assert result == BroadcastResult(sent=1, failed=1)
    assert [call[0] for call in bot.calls] == [1, 2]
    assert all(call[1].startswith(STANDARD_NOTIFICATION_TEXT) for call in bot.calls)
    assert "Ресурсы не обновлялись с 03:00 понедельника" in bot.calls[0][1]
    assert [
        button.callback_data
        for row in bot.calls[0][2].keyboard
        for button in row
    ] == ["user_data/fill/resources", "home"]


def test_standard_notification_ignores_stale_technologies(monkeypatch):
    user = UserData(user_id=1, username="current")
    user.mark_updated("hammers", date(2026, 8, 2))
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: FakeUserDataDB([user]),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.now",
        lambda: datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_active_admin_group",
        lambda user_id: AccessGroup(-100123, "Test clan"),
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    bot = FakeBot()

    plan = build_standard_notification_plan([user], date(2026, 8, 2))
    result = send_standard_notification(bot, plan)

    assert result == BroadcastResult(sent=0, failed=0)
    assert bot.calls == []


def test_standard_notification_uses_same_resource_filter_as_calculator():
    current = UserData(user_id=1, username="current")
    stale = UserData(user_id=2, username="stale")
    technology_only = UserData(user_id=3, username="technology")
    current.mark_updated("hammers", date(2026, 8, 10))
    stale.mark_updated("hammers", date(2026, 8, 9))
    technology_only.mark_updated("forge_level", date(2026, 8, 14))

    plan = build_standard_notification_plan(
        [current, stale, technology_only], date(2026, 8, 10)
    )

    assert [recipient.user_id for recipient in plan.recipients] == [2, 3]
    assert plan.skipped == 1


def test_standard_notification_combines_multiple_accounts(monkeypatch):
    users = [
        UserData(account_id=11, user_id=1, username="one", tag="Alpha"),
        UserData(account_id=22, user_id=1, username="one", tag="Beta"),
    ]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: FakeUserDataDB(users),
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, reply_markup):
            self.calls.append((user_id, text, reply_markup))

    bot = FakeBot()

    plan = build_standard_notification_plan(users, date(2026, 8, 3))
    result = send_standard_notification(bot, plan)

    assert result == BroadcastResult(sent=1, failed=0)
    assert len(bot.calls) == 1
    assert "<b>Alpha</b>" in bot.calls[0][1]
    assert "<b>Beta</b>" in bot.calls[0][1]
    callback_data = [
        button.callback_data
        for row in bot.calls[0][2].keyboard
        for button in row
    ]
    assert callback_data == [
        "accounts/select/resources/11",
        "accounts/select/resources/22",
        "home",
    ]


def test_standard_notification_confirmation_is_compact_and_uses_snapshot(
    monkeypatch,
):
    notification_date = date(2026, 8, 2)
    needs_update = UserData(user_id=1, username="outdated")
    current = UserData(user_id=2, username="current")
    for field in (
        "mount_keys",
        "skills",
        "shells",
        "hammers",
        "pets",
        "unmerged_mounts",
    ):
        current.mark_updated(field, notification_date)
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: FakeUserDataDB([needs_update, current]),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.now",
        lambda: datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_active_admin_group",
        lambda user_id: AccessGroup(-100123, "Test clan"),
    )

    class FakeBot:
        def __init__(self):
            self.data = {}
            self.edited = []

        def set_state(self, user_id, state):
            pass

        def add_data(self, user_id, **kwargs):
            self.data.update(kwargs)

        def edit_message_text(self, *args, **kwargs):
            self.edited.append((args, kwargs))

    bot = FakeBot()

    confirm_standard_notification(make_callback(), bot)

    text = bot.edited[0][0][0]
    markup = bot.edited[0][1]["reply_markup"]
    assert "не обновляли ни один ресурс с 03:00 понедельника" in text
    assert "Получателей: <b>1</b>" in text
    assert "Уже обновили хотя бы один ресурс: <b>1</b>" in text
    assert STANDARD_NOTIFICATION_TEXT not in text
    assert [
        button.text for row in markup.keyboard for button in row
    ] == ["📣 Отправить", "✖️ Отмена"]
    plan = bot.data["standard_notification_plan"]
    assert len(plan.recipients) == 1
    assert plan.skipped == 1


def test_prepared_standard_notification_does_not_read_users_again(monkeypatch):
    plan = build_standard_notification_plan(
        [UserData(user_id=1, username="outdated")],
        date(2026, 8, 2),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected reload")),
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, reply_markup):
            self.calls.append((user_id, text, reply_markup))

    bot = FakeBot()

    result = send_standard_notification(bot, plan)

    assert result == BroadcastResult(sent=1, failed=0)
    assert [call[0] for call in bot.calls] == [1]


def test_standard_notification_shows_progress_before_sending(monkeypatch):
    plan = build_standard_notification_plan(
        [UserData(user_id=1, username="outdated")],
        date(2026, 8, 2),
    )
    sent_plans = []
    monkeypatch.setattr(
        "tg.admins.notifications.send_standard_notification",
        lambda bot, prepared_plan: (
            sent_plans.append(prepared_plan)
            or BroadcastResult(sent=1, failed=0)
        ),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {"is_clan_admin": lambda _, user_id, group_id: True},
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: FakeUserDataDB(
            [UserData(user_id=1, username="outdated")]
        ),
    )
    bot = NotificationFlowBot(
        {"standard_notification_plan": plan, "admin_group_id": -100123}
    )

    send_standard_notification_confirmed(
        make_callback("admins/notifications/send_standard"), bot
    )

    assert bot.edited[0][0][0] == "Отправляю уведомления…"
    assert len(sent_plans) == 1
    assert [recipient.user_id for recipient in sent_plans[0].recipients] == [1]
    assert bot.edited[-1][0][0] == "Уведомления пользователям"


def test_custom_notifications_show_progress_before_sending(monkeypatch):
    group_calls = []
    private_calls = []
    monkeypatch.setattr(
        "tg.admins.notifications.send_custom_notification",
        lambda bot, text, admin_name, group_id, audience: (
            group_calls.append((text, admin_name, group_id, audience))
            or BroadcastResult(sent=1, failed=0)
        ),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.send_custom_private_notification",
        lambda bot, text, admin_name, group_id, audience: (
            private_calls.append((text, admin_name, group_id, audience))
            or BroadcastResult(sent=1, failed=0)
        ),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.get_active_admin_group",
        lambda user_id: AccessGroup(-100123, "Test clan"),
    )

    group_bot = NotificationFlowBot(
        {
            "notification_text": "Текст",
            "admin_name": "Admin",
            "notification_audience": "monday",
            "admin_group_id": -100123,
        }
    )
    send_custom_group_notification_confirmed(
        make_callback("admins/notifications/send_custom_group"), group_bot
    )
    private_bot = NotificationFlowBot(
        {
            "notification_text": "Текст",
            "admin_name": "Admin",
            "notification_audience": "today",
            "admin_group_id": -100123,
        }
    )
    send_custom_private_notification_confirmed(
        make_callback("admins/notifications/send_custom_private"), private_bot
    )

    assert group_bot.edited[0][0][0] == "Отправляю уведомление в группу…"
    assert private_bot.edited[0][0][0] == "Отправляю личные уведомления…"
    assert group_calls == [
        (
            "Текст",
            "Admin",
            -100123,
            CustomNotificationAudience.NOT_UPDATED_SINCE_MONDAY,
        )
    ]
    assert private_calls == [
        (
            "Текст",
            "Admin",
            -100123,
            CustomNotificationAudience.NOT_UPDATED_TODAY,
        )
    ]


def test_revoked_admin_cannot_send_pinned_custom_notification(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "tg.admins.notifications.get_admins_db",
        lambda: SimpleNamespace(
            is_clan_admin=lambda user_id, group_id: False
        ),
    )
    monkeypatch.setattr(
        "tg.admins.notifications.send_custom_notification",
        lambda *args: sent.append(args),
    )
    bot = NotificationFlowBot(
        {
            "notification_text": "Текст",
            "admin_name": "Admin",
            "notification_audience": "all",
            "admin_group_id": -100123,
        }
    )

    send_custom_group_notification_confirmed(
        make_callback("admins/notifications/send_custom_group"), bot
    )

    assert sent == []
    assert bot.deleted_states == [42]
    assert bot.answers[-1][0][1] == (
        "Нет прав администратора выбранного клана"
    )
    assert bot.answers[-1][1]["show_alert"] is True


def test_custom_notification_audience_can_be_selected():
    bot = NotificationFlowBot(
        {
            "notification_text": "Текст",
            "admin_name": "Admin",
            "admin_group_id": -100123,
        }
    )

    select_custom_notification_audience(
        make_callback("admins/notifications/custom_audience/monday"), bot
    )

    assert bot.data["notification_audience"] == "monday"
    assert "не обновлявшие ресурсы с 03:00 понедельника" in (
        bot.edited[0][0][0]
    )
    assert [
        button.callback_data
        for row in bot.edited[0][1]["reply_markup"].keyboard
        for button in row
    ] == [
        "admins/notifications/send_custom_group",
        "admins/notifications/send_custom_private",
        "admins/notifications",
    ]


def test_custom_notification_prompts_for_audience_after_text():
    message = make_callback().message
    message.text = "Текст"

    class FakeBot(NotificationFlowBot):
        def __init__(self):
            super().__init__({"admin_group_id": -100123})
            self.sent = []

        def send_message(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    bot = FakeBot()

    receive_custom_notification_text(message, bot)

    assert [
        button.callback_data
        for row in bot.sent[0][1]["reply_markup"].keyboard
        for button in row
    ] == [
        "admins/notifications/custom_audience/all",
        "admins/notifications/custom_audience/today",
        "admins/notifications/custom_audience/monday",
        "admins/notifications",
    ]


def test_custom_notification_audience_filters_by_last_resource_update():
    today = UserData(user_id=1, username="today")
    monday = UserData(user_id=2, username="monday")
    stale = UserData(user_id=3, username="stale")
    today.mark_updated("hammers", date(2026, 8, 14))
    monday.mark_updated("skills", date(2026, 8, 10))
    stale.mark_updated("forge_level", date(2026, 8, 14))
    users = [today, monday, stale]
    reference = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)

    not_updated_today = filter_custom_notification_users(
        users,
        CustomNotificationAudience.NOT_UPDATED_TODAY,
        reference,
    )
    not_updated_since_monday = filter_custom_notification_users(
        users,
        CustomNotificationAudience.NOT_UPDATED_SINCE_MONDAY,
        reference,
    )

    assert [user.user_id.value for user in not_updated_today] == [2, 3]
    assert [
        user.user_id.value for user in not_updated_since_monday
    ] == [3]


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


def test_custom_notification_mentions_user_once_for_multiple_accounts():
    users = [
        UserData(account_id=11, user_id=1, username="one", tag="Alpha"),
        UserData(account_id=22, user_id=1, username="one", tag="Beta"),
    ]

    combined = "\n".join(
        build_custom_notification_messages("Проверка", "Admin", users)
    )

    assert combined.count('tg://user?id=1') == 1
    assert "one (Alpha, Beta)" in combined


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
    users = [UserData(user_id=1, username="one", tag="Лидер")]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db", lambda: FakeUserDataDB(users)
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, group_id, text, disable_notification):
            self.calls.append((group_id, text, disable_notification))

    bot = FakeBot()

    result = send_custom_notification(
        bot, "Важный текст", "Admin", -100123
    )

    assert result == BroadcastResult(sent=1, failed=0)
    assert bot.calls[0][0] == -100123
    assert bot.calls[0][2] is False
    assert "tg://user?id=1" in bot.calls[0][1]
    assert "one (Лидер)" in bot.calls[0][1]


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
        bot, "Личный <текст>", "Admin & owner", -100123
    )

    assert result == BroadcastResult(sent=1, failed=1)
    assert [call[0] for call in bot.calls] == [1, 2]
    assert all(call[2] is False for call in bot.calls)
    assert "Личный &lt;текст&gt;" in bot.calls[0][1]
    assert "Admin &amp; owner" in bot.calls[0][1]
    assert "tg://user?id=" not in bot.calls[0][1]


def test_custom_private_notification_is_sent_once_for_multiple_accounts(
    monkeypatch,
):
    users = [
        UserData(account_id=11, user_id=1, username="one", tag="Alpha"),
        UserData(account_id=22, user_id=1, username="one", tag="Beta"),
    ]
    monkeypatch.setattr(
        "tg.admins.notifications.get_user_data_db",
        lambda: FakeUserDataDB(users),
    )

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, disable_notification):
            self.calls.append((user_id, text, disable_notification))

    bot = FakeBot()

    result = send_custom_private_notification(bot, "Текст", "Admin", -100123)

    assert result == BroadcastResult(sent=1, failed=0)
    assert [call[0] for call in bot.calls] == [1]
