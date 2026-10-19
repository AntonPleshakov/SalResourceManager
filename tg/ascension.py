from decimal import Decimal, ROUND_CEILING

from telebot import TeleBot
from telebot.types import CallbackQuery

from db.initializer import get_user_data_db
from resources.egg_levels import EggLevel
from resources.ascension import (
    RARITIES, AscensionForecast, available_summons, forecast_ascension,
    resource_inputs, summons_to_level, target_resource_cost,
)
from resources.war_rules.mount_packages import summon_packages
from resources.user_data import UserData
from tg.handlers import HandlerRegistry
from tg.rich import (
    account_context, back_button, button_row, callback_button,
    deliver_rich_message, details, heading, input_rich_message,
)
from tg.utils import get_ids


TITLES = {"skills": "📜 Навыки", "pets": "🐾 Питомцы", "mount": "🐎 Маунты"}
RESOURCE_NAMES = {"skills": "🎟️ Билеты", "pets": "🥚 Скорлупа", "mount": "🔑 Ключи"}


def _number(value: Decimal | int) -> str:
    return format(Decimal(value).normalize(), ",f").replace(",", " ").replace(".", ",")


def _rarity_label(rarity: str) -> str:
    return f"{EggLevel[rarity.upper()].color_icon} {rarity}"


def _forecast_block(result: AscensionForecast, missing: int) -> str:
    rarity_index = max(index for index, chance in enumerate(result.probabilities) if chance > 0)
    rarity = _rarity_label(RARITIES[rarity_index])
    chance = _number(result.probabilities[rarity_index])
    status = (
        "✅ Можно возносить"
        if result.favorable else "⏳ Лучше подкопить"
    )
    shortage = (
        f"<br>{RESOURCE_NAMES[result.system]}: ещё <b>{_number(missing)}</b>"
        if missing else ""
    )
    maximum = " 🏁" if result.level == 100 else ""
    return "".join((
        heading(f"{TITLES[result.system]} · ур. {result.level} / 100{maximum}", level=3),
        f"<p>{rarity} · <b>{chance}%</b><br><b>{status}</b>{shortage}</p>",
    ))


def _forecast_details(user: UserData, result: AscensionForecast, target_cost: int) -> str:
    system = result.system
    amount, discount, extra = resource_inputs(user, system)
    expected = available_summons(system, amount, discount, extra)
    lines = [f"{RESOURCE_NAMES[system]}: <b>{_number(amount)}</b>"]
    if system == "skills":
        cost = Decimal(40) * (100 - discount) / 100
        lines.extend((
            f"Цена призыва: 40 × (1 − {discount} / 100) = {_number(cost)}",
            f"Призывы: ⌊{_number(amount)} ÷ {_number(cost)}⌋ = {_number(expected)}",
        ))
    else:
        if system == "pets":
            base = amount // 100
            lines.append(f"Покупки яиц: ⌊{_number(amount)} ÷ 100⌋ = {_number(base)}")
        else:
            base, remaining, packages = summon_packages(amount, discount)
            lines.append(f"Скидка на пакеты: {discount}% (цена округляется вверх)")
            lines.extend(packages)
            lines.append(f"Всего: {_number(base)} маунтов; остаток: {_number(remaining)} ключей")
        lines.append(
            f"С бонусом {extra}%: {_number(base)} × (1 + {extra} / 100) = {_number(expected)}"
        )
    spent = summons_to_level(system, result.level)
    lines.append(f"Ур. {result.level}: сумма призывов по таблице = {_number(spent)}")
    if result.level < 100:
        next_cost = summons_to_level(system, result.level + 1)
        lines.append(f"{_number(spent)} ≤ {_number(expected)} &lt; {_number(next_cost)} → ур. {result.level}")
    else:
        lines.append(f"{_number(expected)} ≥ {_number(spent)} → ур. 100 🏁")
    target_summons = summons_to_level(system, result.target_level)
    target_chance = "2" if system == "skills" else "7,2"
    lines.append(
        f"Восстановление силы: {_rarity_label(result.target_rarity)} от {target_chance}% · ур. {result.target_level}"
    )
    if system == "skills":
        lines.append(f"Нужно билетов: ⌈{_number(target_summons)} × {_number(cost)}⌉ = {_number(target_cost)}")
    elif system == "pets":
        lines.append(
            f"Нужно скорлупы: ⌈{_number(target_summons)} ÷ (1 + {extra} / 100)⌉ × 100 = {_number(target_cost)}"
        )
    else:
        purchases = (Decimal(target_summons) / (1 + Decimal(extra) / 100)).to_integral_value(rounding=ROUND_CEILING)
        lines.append(f"Нужно купить: ⌈{_number(target_summons)} ÷ (1 + {extra} / 100)⌉ = {_number(purchases)} маунтов")
        lines.extend(summon_packages(target_cost, discount)[2])
        lines.append(f"Минимальный запас для этих пакетов: {_number(target_cost)} ключей")
    lines.append(f"Нехватка: max({_number(target_cost)} − {_number(amount)}, 0) = <b>{_number(max(target_cost - amount, 0))}</b>")
    return heading(TITLES[system], level=3) + "<p>" + "<br>".join(lines) + "</p>"


def ascension_text(user: UserData) -> str:
    results = forecast_ascension(user)
    costs = {result.system: target_resource_cost(user, result.system) for result in results}
    calculation_details = "<hr>".join(
        _forecast_details(user, result, costs[result.system]) for result in results
    )
    return "".join((
        heading("✨ Вознесение"), account_context(str(user.tag.value)),
        "<p>Ваш прогноз после сброса</p>",
        "<hr>".join(
            _forecast_block(result, max(costs[result.system] - resource_inputs(user, result.system)[0], 0))
            for result in results
        ),
        details("🔎 Подробнее о расчёте", calculation_details),
        button_row((callback_button("📦 Обновить ресурсы", "resources"),
                    callback_button("🔬 Технологии", "technologies"))),
        back_button("🏠 Главное меню", "home"),
    ))


def ascension_menu(callback_query: CallbackQuery, bot: TeleBot) -> None:
    user = get_user_data_db().get_assigned_user(get_ids(callback_query)[0])
    if user is None:
        parts = (
            heading("✨ Вознесение"),
            "<p>Сначала выберите игровой аккаунт и клан.</p>",
            button_row((callback_button("🎮 Игровые аккаунты", "accounts"),)),
            back_button("🏠 Главное меню", "home"),
        )
    else:
        parts = (ascension_text(user),)
    deliver_rich_message(callback_query, bot, input_rich_message(parts))


def register_handlers(bot: TeleBot) -> None:
    HandlerRegistry(bot).private_callback(ascension_menu, button="ascension")
