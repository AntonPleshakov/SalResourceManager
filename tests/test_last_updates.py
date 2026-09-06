from datetime import date, datetime
from pathlib import Path

from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.admins.resource_status import build_last_updates_report


def test_last_updates_report_uses_latest_field_and_readable_age(monkeypatch):
    current = UserData(user_id=42, username="tester", tag="Лидер")
    current.mark_updated("mount_keys", date(2026, 8, 8))
    current.mark_updated("hammers", date(2026, 8, 12))
    yesterday = UserData(user_id=43, username="second")
    yesterday.mark_updated("pets", date(2026, 8, 13))
    never = UserData(user_id=44, username="new")
    monkeypatch.setattr(
        "common.datetime_utils.now", lambda: datetime(2026, 8, 14, 12)
    )

    report = build_last_updates_report([current, yesterday, never])

    assert "<h2>Последнее обновление ресурсов</h2>" in report
    assert "<aside>Всего аккаунтов<br><b>3</b></aside>" in report
    assert "tester (Лидер)</a><br><i>2 дня назад (12.08.2026)</i>" in report
    assert "second</a><br><i>вчера (13.08.2026)</i>" in report
    assert "new</a><br><i>никогда</i>" in report
    assert "tg://user?id=42" in report
    assert report.index("second</a>") < report.index("tester (")
    assert report.index("tester (") < report.index("new</a>")
