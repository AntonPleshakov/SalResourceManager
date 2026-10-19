from decimal import Decimal
from types import SimpleNamespace

import pytest

from resources.ascension import (
    LEVEL_DATA, available_summons, forecast_ascension, forecast_level,
    resource_inputs, summons_to_level, target_resource_cost,
)
from resources.user_data import UserData
from tests.test_war_menu import FakeBot, make_callback
from tg.ascension import ascension_menu, ascension_text, register_handlers


@pytest.mark.parametrize("system,total", [("skills", 9600), ("pets", 1935), ("mount", 1980)])
def test_all_level_boundaries_and_full_cycle(system, total):
    spent = 0
    for row in LEVEL_DATA[system][:-1]:
        level, required, *_ = row
        assert forecast_level(system, Decimal(spent)).level == level
        assert forecast_level(system, Decimal(spent + required) - Decimal("0.01")).level == level
        spent += required
        assert forecast_level(system, Decimal(spent)).level == level + 1
    assert spent == total
    assert forecast_level(system, Decimal(total * 2)).level == 100


def test_forum_targets_without_technologies():
    results = forecast_ascension(UserData(skills=49_600, shells=48_600, mount_keys=30_000))
    assert [result.level for result in results] == [24, 37, 31]
    assert all(result.favorable for result in results)
    assert results[0].probabilities[3] == 2
    assert results[1].probabilities[3] == Decimal("7.2")
    assert results[2].probabilities[2] == Decimal("7.2")


def test_personal_technologies_and_extra_drops_advance_levels():
    results = forecast_ascension(UserData(
        skills=37_200, skill_summon_cost=25,
        shells=32_400, extra_egg_chance=50,
        mount_keys=15_000, mount_summon_cost=25, extra_mount_chance=50,
    ))
    assert [result.level for result in results] == [24, 37, 31]


def test_unaffordable_summons_and_fractional_bonus():
    results = forecast_ascension(UserData(skills=39, shells=199, mount_keys=37,
                                          extra_egg_chance=50, mount_summon_cost=25))
    assert [result.level for result in results] == [1, 1, 1]
    assert results[1].progress == Decimal("1.5")
    assert results[2].progress == 0
    assert all(not result.favorable for result in results)


def test_rounded_mount_package_price():
    result = forecast_ascension(UserData(mount_keys=38, mount_summon_cost=25))[2]
    assert result.progress == 1


def test_rendering_uses_forecast_and_escapes_account_name():
    text = ascension_text(UserData(tag="<test>", skills=49_600, shells=7_100))
    assert "&lt;test&gt;" in text
    assert "📜 Навыки · ур. 24 / 100" in text
    assert "Промежуточный" not in text and "промежуточный" not in text
    assert "не гарантированы" not in text
    assert 'data="home"' in text
    summary, expanded = text.split('<details>', 1)
    assert "✅ Можно возносить" in summary
    assert "⏳ Лучше подкопить" in summary
    assert "🟡 Legendary · <b>2%</b>" in summary
    assert "🟢 Epic · <b>20%</b>" in summary
    assert "🥚 Скорлупа: ещё <b>41 500</b>" in summary
    assert "Восстановление силы" not in summary
    assert "Билеты:" not in summary
    assert "Билеты: <b>49 600</b>" in expanded
    assert "До следующего уровня" not in expanded
    assert "Цена призыва: 40 × (1 − 0 / 100) = 40" in expanded
    assert "⌊49 600 ÷ 40⌋ = 1 240" in expanded
    assert "1 240 ≤ 1 240 &lt; 1 350 → ур. 24" in expanded
    assert "Нехватка: max(48 600 − 7 100, 0) = <b>41 500</b>" in expanded
    assert "Восстановление силы: 🟡 Legendary" in expanded
    assert '<summary>🔎 Подробнее о расчёте</summary>' in text


@pytest.mark.parametrize("discount,extra", [(0, 0), (25, 50), (13, 26)])
def test_shortage_is_minimum_budget_that_reaches_target(discount, extra):
    user = UserData(skill_summon_cost=discount, mount_summon_cost=discount,
                    extra_egg_chance=extra, extra_mount_chance=extra)
    for system in ("skills", "pets", "mount"):
        cost = target_resource_cost(user, system)
        _, actual_discount, actual_extra = resource_inputs(user, system)
        target_level = forecast_level(system, Decimal(0)).target_level
        required = summons_to_level(system, target_level)
        assert available_summons(system, cost, actual_discount, actual_extra) >= required
        assert available_summons(system, cost - 1, actual_discount, actual_extra) < required


def test_menu_reads_requesting_account(monkeypatch):
    requested = []

    def get_user(user_id):
        requested.append(user_id)
        return UserData(user_id=user_id, tag="Активный", skills=49_600)

    monkeypatch.setattr("tg.ascension.get_user_data_db", lambda: SimpleNamespace(get_assigned_user=get_user))
    bot = FakeBot()
    ascension_menu(make_callback(42, "ascension"), bot)
    assert requested == [42]
    assert "Активный" in bot.edited[0][0]
    assert "24 / 100" in bot.edited[0][0]


def test_menu_without_account_and_registration(monkeypatch):
    monkeypatch.setattr("tg.ascension.get_user_data_db", lambda: SimpleNamespace(get_assigned_user=lambda _: None))
    bot = FakeBot()
    ascension_menu(make_callback(42, "ascension"), bot)
    assert 'data="accounts"' in bot.edited[0][0]
    registered = []
    register_handlers(SimpleNamespace(register_callback_query_handler=lambda handler, **filters: registered.append(filters)))
    assert len(registered) == 1
    assert registered[0]["is_private"] is True
    assert registered[0]["button"] == "ascension"
