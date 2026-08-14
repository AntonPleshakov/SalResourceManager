from datetime import date
from pathlib import Path

from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.admins.resource_status import (
    build_last_updates_report,
    build_stale_resources_report,
)


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

    assert "Последнее обновление аккаунтов" in report
    assert "tester (Лидер)</a> — 2 дня назад (12.08.2026)" in report
    assert "second</a> — вчера (13.08.2026)" in report
    assert "new</a> — никогда" in report
    assert "tg://user?id=42" in report


def test_stale_report_lists_only_old_or_never_updated_resources():
    user = UserData(user_id=42, username="tester", tag="Лидер")
    user.mark_updated("mount_keys", date(2026, 8, 2))
    user.mark_updated("skills", date(2026, 8, 1))
    user.mark_updated("shells", date(2026, 7, 31))
    user.mark_updated("forge_level", date(2026, 8, 1))

    report = build_stale_resources_report(
        [user],
        reference_date=date(2026, 8, 8),
        stale_after_days=7,
    )

    assert "Ключи маунтов" not in report
    assert "Билетики навыков — 01.08.2026" in report
    assert "Скорлупа — 31.07.2026" in report
    assert "Уровень кузницы — 01.08.2026" in report
    assert "tg://user?id=42" in report
    assert "tester (Лидер)" in report
    assert "Дата отчёта" not in report


def test_stale_report_says_when_everything_is_current():
    user = UserData(user_id=42, username="tester")
    for field_name in (
        "mount_keys",
        "skills",
        "shells",
        "hammers",
        "pets",
        "unmerged_mounts",
        "forge_level",
        "skill_summon_cost",
        "extra_egg_chance",
        "mount_summon_cost",
        "extra_mount_chance",
    ):
        user.mark_updated(field_name, date(2026, 8, 8))

    report = build_stale_resources_report(
        [user],
        reference_date=date(2026, 8, 8),
        stale_after_days=7,
    )

    assert "Все пользователи обновляют данные вовремя" in report
