from datetime import datetime, timezone
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.metrics import ApplicationMetrics
from tg.reminders import (
    ReminderKind,
    ScheduledReminder,
    _account_reminder_message,
    _account_reminder_text,
    _reminder_buttons,
    _required_field_names,
    next_reminder,
    send_reminder,
)


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def account_reminder_text(reminder: ScheduledReminder) -> str:
    user = UserData(account_id=1, user_id=1, tag="Alpha")
    return _account_reminder_text(
        reminder,
        [(user, _required_field_names())],
    )


@pytest.mark.parametrize(
    ("moment", "expected_time"),
    [
        (dt(2026, 8, 3, 12), dt(2026, 8, 3, 13)),
        (dt(2026, 8, 3, 14), dt(2026, 8, 10, 13)),
        (dt(2026, 8, 4, 12), dt(2026, 8, 10, 13)),
        (dt(2026, 8, 9, 14), dt(2026, 8, 10, 13)),
    ],
)
def test_next_reminder_is_only_scheduled_on_monday(moment, expected_time):
    reminder = next_reminder(moment)

    assert reminder == ScheduledReminder(
        expected_time,
        ReminderKind.WEEKLY_REWARD,
    )


def test_next_reminder_requires_timezone():
    with pytest.raises(ValueError):
        next_reminder(datetime(2026, 8, 3, 12))


def test_next_reminder_validates_hour():
    with pytest.raises(ValueError):
        next_reminder(dt(2026, 8, 3), 24)


def test_weekly_reminder_mentions_received_resources():
    text = account_reminder_text(
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD)
    )

    assert "полученные в награду" in text
    assert "за войну и личный турнир" in text
    assert "<li>Билетики навыков</li>" in text
    assert "<li>Молотки</li>" in text
    assert "Шанс на доп. маунта" not in text


def test_reminder_has_embedded_navigation_buttons():
    html = _reminder_buttons({"extra_mount_chance", "hammers"})

    assert 'data="user_data/fill/tracked/3,10"' in html
    assert 'data="resources"' in html
    assert 'data="technologies"' in html
    assert 'data="pets"' in html
    assert 'data="home"' in html
    assert 'style="primary"' in html


def test_send_reminder_sends_to_every_user_and_continues_after_error(monkeypatch):
    class FakeUserDataDB:
        def get_attached_clan_ids(self):
            return []

        def get_assigned_users_with_reminders_enabled(self):
            return [UserData(user_id=1), UserData(user_id=2)]

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_rich_message(self, user_id, rich_message):
            self.calls.append((user_id, rich_message))
            if user_id == 1:
                raise RuntimeError("blocked")

    monkeypatch.setattr("tg.reminders.get_user_data_db", lambda: FakeUserDataDB())
    bot = FakeBot()
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)

    send_reminder(
        bot,
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD),
        metrics,
    )

    assert [call[0] for call in bot.calls] == [1, 2]
    assert registry.get_sample_value(
        "srm_reminders_total",
        {"kind": "weekly_reward", "result": "sent"},
    ) == 1
    assert registry.get_sample_value(
        "srm_reminders_total",
        {"kind": "weekly_reward", "result": "failed"},
    ) == 1


def test_blocking_bot_disables_future_monday_reminders(monkeypatch):
    class BlockedError(Exception):
        error_code = 403
        description = "Forbidden: bot was blocked by the user"

    class FakeUserDataDB:
        def __init__(self):
            self.disabled = []

        def get_attached_clan_ids(self):
            return []

        def get_assigned_users_with_reminders_enabled(self):
            return [UserData(user_id=1, username="blocked")]

        def set_reminders_enabled(self, user_id, enabled):
            self.disabled.append((user_id, enabled))

    class FakeBot:
        def send_rich_message(self, _user_id, _rich_message):
            raise BlockedError()

    database = FakeUserDataDB()
    monkeypatch.setattr("tg.reminders.ApiTelegramException", BlockedError)
    monkeypatch.setattr("tg.reminders.get_user_data_db", lambda: database)

    send_reminder(
        FakeBot(),
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD),
    )

    assert database.disabled == [(1, False)]


def test_reminder_combines_multiple_accounts_into_one_message(monkeypatch):
    users = [
        UserData(account_id=11, user_id=1, username="one", tag="Alpha"),
        UserData(account_id=22, user_id=1, username="one", tag="Beta"),
    ]

    class FakeUserDataDB:
        def get_attached_clan_ids(self):
            return []

        def get_assigned_users_with_reminders_enabled(self):
            return users

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_rich_message(self, user_id, rich_message):
            self.calls.append((user_id, rich_message))

    monkeypatch.setattr("tg.reminders.get_user_data_db", lambda: FakeUserDataDB())
    bot = FakeBot()

    send_reminder(
        bot,
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD),
    )

    assert len(bot.calls) == 1
    assert bot.calls[0][0] == 1
    html = bot.calls[0][1].html
    assert "<h3>Alpha</h3>" in html
    assert "<h3>Beta</h3>" in html
    assert 'data="accounts/select/resources/11"' in html
    assert 'data="accounts/select/resources/22"' in html
    assert 'data="home"' in html
    assert (
        html.index("<h3>Alpha</h3>")
        < html.index('data="accounts/select/resources/11"')
        < html.index("<h3>Beta</h3>")
        < html.index('data="accounts/select/resources/22"')
    )


def test_weekly_reminder_skips_current_user_and_lists_missing_resources(
    monkeypatch,
):
    reminder = ScheduledReminder(
        dt(2026, 8, 3, 13),
        ReminderKind.WEEKLY_REWARD,
    )
    current_user = UserData(user_id=1, username="current")
    partial_user = UserData(user_id=2, username="partial")
    for resource_name in _required_field_names():
        current_user.mark_updated(resource_name, reminder.time.date())
    partial_user.mark_updated("hammers", reminder.time.date())

    class FakeUserDataDB:
        def get_attached_clan_ids(self):
            return []

        def get_assigned_users_with_reminders_enabled(self):
            return [current_user, partial_user]

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_rich_message(self, user_id, rich_message):
            self.calls.append((user_id, rich_message))

    monkeypatch.setattr("tg.reminders.get_user_data_db", lambda: FakeUserDataDB())
    bot = FakeBot()

    send_reminder(bot, reminder)

    assert [call[0] for call in bot.calls] == [2]
    assert "Билетики навыков" in bot.calls[0][1].html
    assert "Молотки" not in bot.calls[0][1].html


def test_reminder_escapes_account_name_and_embeds_buttons():
    reminder = ScheduledReminder(
        dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD
    )
    user = UserData(account_id=7, user_id=1, tag='Alpha <& "one"')

    message = _account_reminder_message(
        reminder,
        [(user, {"hammers"})],
    )

    assert "Alpha &lt;&amp; &quot;one&quot;" in message.html
    assert 'data="user_data/fill/tracked/3"' in message.html
    assert message.skip_entity_detection
