from datetime import date
from pathlib import Path

from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.admins.resource_status import build_last_updates_report


def test_last_updates_report_uses_latest_field_and_readable_age():
    current = UserData(user_id=42, username="tester", tag="Лидер")
    current.mark_updated("mount_keys", date(2026, 8, 8))
    current.mark_updated("hammers", date(2026, 8, 12))
    yesterday = UserData(user_id=43, username="second")
    yesterday.mark_updated("pets", date(2026, 8, 13))
    never = UserData(user_id=44, username="new")

    report = build_last_updates_report(
        [current, yesterday, never],
        reference_date=date(2026, 8, 14),
    )

    assert "<b>Последнее обновление аккаунтов (всего: 3)</b>" in report
    assert "tester (Лидер)</a> — 2 дня назад (12.08.2026)" in report
    assert "second</a> — вчера (13.08.2026)" in report
    assert "new</a> — никогда" in report
    assert "tg://user?id=42" in report
    assert report.index("second</a>") < report.index("tester (")
    assert report.index("tester (") < report.index("new</a>")
