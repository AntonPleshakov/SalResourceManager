from datetime import datetime, timezone
from pathlib import Path

import pytest

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from resources.war import DEFAULT_WAR_STAGES, WarActivity
from tg.reminders import (
    ReminderKind,
    ScheduledReminder,
    _reminder_text,
    next_reminder,
    send_reminder,
)


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("moment", "expected_time", "kind", "war_day"),
    [
        (
            dt(2026, 8, 3, 12),
            dt(2026, 8, 3, 13),
            ReminderKind.WEEKLY_REWARD,
            None,
        ),
        (dt(2026, 8, 3, 14), dt(2026, 8, 5, 13), ReminderKind.DAILY, 1),
        (dt(2026, 8, 4, 12), dt(2026, 8, 5, 13), ReminderKind.DAILY, 1),
        (dt(2026, 8, 8, 14), dt(2026, 8, 9, 13), ReminderKind.DAILY, 5),
        (
            dt(2026, 8, 9, 14),
            dt(2026, 8, 10, 13),
            ReminderKind.WEEKLY_REWARD,
            None,
        ),
    ],
)
def test_next_reminder(moment, expected_time, kind, war_day):
    reminder = next_reminder(moment)

    assert reminder == ScheduledReminder(expected_time, kind, war_day)


def test_next_reminder_requires_timezone():
    with pytest.raises(ValueError):
        next_reminder(datetime(2026, 8, 3, 12))


def test_daily_reminder_mentions_configured_war_stages(monkeypatch):
    class FakeWarStagesDB:
        def get_stages(self):
            return DEFAULT_WAR_STAGES

    monkeypatch.setattr(
        "tg.reminders.get_war_stages_db", lambda: FakeWarStagesDB()
    )

    text = _reminder_text(
        ScheduledReminder(dt(2026, 8, 5, 13), ReminderKind.DAILY, 1)
    )

    assert "1-го дня войны" in text
    assert "Ковка, Подземелья, Навыки" in text
    assert "Могли быть потрачены:" in text
    assert "• Билетики навыков" in text
    assert "• Молотки" in text
    assert "Ключи маунтов" not in text


def test_daily_reminder_deduplicates_resources_and_keeps_catalog_order(monkeypatch):
    class FakeWarStagesDB:
        def get_stages(self):
            return {
                3: (
                    WarActivity.PETS,
                    WarActivity.MOUNTS,
                    WarActivity.PETS,
                )
            }

    monkeypatch.setattr(
        "tg.reminders.get_war_stages_db", lambda: FakeWarStagesDB()
    )

    text = _reminder_text(
        ScheduledReminder(dt(2026, 8, 7, 13), ReminderKind.DAILY, 3)
    )

    assert text.count("• Скорлупа") == 1
    assert text.index("• Ключи маунтов") < text.index("• Скорлупа")
    assert text.index("• Скорлупа") < text.index("• Питомцы")
    assert text.index("• Питомцы") < text.index("• Необъединённые маунты")


def test_daily_reminder_explains_when_no_tracked_resource_is_spent(monkeypatch):
    class FakeWarStagesDB:
        def get_stages(self):
            return {
                2: (
                    WarActivity.DUNGEONS,
                    WarActivity.FORGE,
                    WarActivity.TECHNOLOGIES,
                )
            }

    monkeypatch.setattr(
        "tg.reminders.get_war_stages_db", lambda: FakeWarStagesDB()
    )

    text = _reminder_text(
        ScheduledReminder(dt(2026, 8, 6, 13), ReminderKind.DAILY, 2)
    )

    assert "нет отслеживаемых расходуемых ресурсов" in text


def test_weekly_reminder_mentions_received_resources():
    text = _reminder_text(
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD)
    )

    assert "полученные в награду" in text
    assert "за войну и личный турнир" in text


def test_send_reminder_sends_to_every_user_and_continues_after_error(monkeypatch):
    class FakeUserDataDB:
        def get_users(self):
            return [UserData(user_id=1), UserData(user_id=2)]

    class FakeBot:
        def __init__(self):
            self.calls = []

        def send_message(self, user_id, text, reply_markup):
            self.calls.append((user_id, text, reply_markup))
            if user_id == 1:
                raise RuntimeError("blocked")

    monkeypatch.setattr("tg.reminders.get_user_data_db", lambda: FakeUserDataDB())
    bot = FakeBot()

    send_reminder(
        bot,
        ScheduledReminder(dt(2026, 8, 3, 13), ReminderKind.WEEKLY_REWARD),
    )

    assert [call[0] for call in bot.calls] == [1, 2]
