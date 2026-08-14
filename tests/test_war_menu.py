from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from resources.war import WAR_STAGES, WarActivity, WarPointsCalculator
from tg.navigation import home
from tg.utils import format_points
from tg.war import (
    personal_war_activity_details,
    personal_war_details_menu,
    personal_war_points,
    public_war_points,
    war_menu,
)


def make_callback(user_id: int = 42, data: str = "war_calculator") -> CallbackQuery:
    user = User(user_id, False, "Tester", username="tester")
    chat = Chat(user_id, "private")
    message = Message(1, user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted_states = []

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edited.append((text, chat_id, message_id, reply_markup))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)


class FakeUserDataDB:
    def __init__(self, user=None):
        self.user = user

    def get_user(self, user_id):
        if self.user is not None and self.user.user_id.value == user_id:
            return self.user
        return None

    def get_users(self):
        return [self.user] if self.user is not None else []


def callback_data(markup):
    return [button.callback_data for row in markup.keyboard for button in row]


def test_home_contains_single_war_points_menu(monkeypatch):
    monkeypatch.setattr("tg.navigation.show_new_user_welcome", lambda *_: False)
    monkeypatch.setattr("tg.navigation.show_unseen_releases", lambda *_: False)
    monkeypatch.setattr(
        "tg.navigation.get_admins_db",
        lambda: type("Admins", (), {"is_admin": lambda self, user_id: False})(),
    )
    monkeypatch.setattr(
        "tg.navigation.get_user_data_db",
        lambda: SimpleNamespace(
            get_accounts=lambda _user_id: [
                SimpleNamespace(tag="Лидер", is_active=True)
            ],
            reminders_enabled=lambda _user_id: True,
        ),
    )
    bot = FakeBot()

    home(make_callback().message, bot)

    buttons = callback_data(bot.sent[0][2])
    assert "accounts" in buttons
    assert "pets" in buttons
    assert "war_menu" in buttons
    assert "releases" in buttons
    assert "war_calculator" not in buttons
    assert "war" not in buttons


def test_war_points_menu_contains_both_calculations():
    bot = FakeBot()

    war_menu(make_callback(data="war_menu"), bot)

    text, _, _, markup = bot.edited[0]
    assert "Очки войны" in text
    assert callback_data(markup) == ["war_calculator", "war", "home"]


def test_personal_war_calculator_uses_requesting_users_data(monkeypatch):
    user = UserData(
        user_id=42,
        username="tester",
        mount_keys=2500,
        skills=1000,
        shells=400,
        hammers=300,
        pets=2,
        unmerged_mounts=3,
        forge_level=10,
        skill_summon_cost=10,
        extra_egg_chance=5,
        mount_summon_cost=10,
        extra_mount_chance=10,
    )
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB(user))
    bot = FakeBot()

    personal_war_points(make_callback(user.user_id.value), bot)

    expected = WarPointsCalculator().calculate([user], WAR_STAGES)
    text, _, _, markup = bot.edited[0]
    assert "Калькулятор очков войны" in text
    first_day_points = expected.points_by_day[1]
    first_day_details = "\n".join(
        f"• {activity.title}: <b>{format_points(points)}</b>"
        for activity, points in expected.points_by_activity_by_day[1].items()
    )
    assert (
        f"<b>День 1: {format_points(first_day_points)}</b>\n"
        f"{first_day_details}"
    ) in text
    assert "<b>Итого по активностям</b>" in text
    assert f"Всего: <b>{format_points(expected.total)}</b>" in text
    assert "war_calculator/details" in callback_data(markup)
    assert "resources" in callback_data(markup)
    assert "technologies" in callback_data(markup)
    assert "pets" in callback_data(markup)
    assert "war_menu" in callback_data(markup)


def test_personal_war_details_menu_lists_every_configured_activity(monkeypatch):
    user = UserData(user_id=42, username="tester", forge_level=1)
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB(user))
    bot = FakeBot()

    personal_war_details_menu(
        make_callback(user.user_id.value, "war_calculator/details"), bot
    )

    text, _, _, markup = bot.edited[0]
    buttons = callback_data(markup)
    assert "Подробный расчёт" in text
    assert {
        f"war_calculator/details/{activity.value}" for activity in WarActivity
    }.issubset(buttons)
    assert buttons[-1] == "war_calculator"


def test_personal_war_activity_details_explain_resources_and_formula(monkeypatch):
    user = UserData(
        user_id=42,
        username="tester",
        forge_level=10,
        hammers=300,
    )
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB(user))
    bot = FakeBot()

    personal_war_activity_details(
        make_callback(user.user_id.value, "war_calculator/details/forging"),
        bot,
    )

    text, _, _, markup = bot.edited[0]
    assert "<b>Ковка</b>" in text
    assert "Дни войны: 1, 3, 5" in text
    assert "Молотки: 300" in text
    assert "Уровень кузницы: 10" in text
    assert "Средние очки за один молоток" in text
    assert "очков" in text
    assert callback_data(markup) == [
        "war_calculator/details",
        "war_calculator",
    ]


def test_forge_details_explain_level_change_between_war_days(monkeypatch):
    user = UserData(user_id=42, username="tester", forge_level=10)
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB(user))
    bot = FakeBot()

    personal_war_activity_details(
        make_callback(user.user_id.value, "war_calculator/details/forge"),
        bot,
    )

    text = bot.edited[0][0]
    assert "Дни войны: 2, 4" in text
    assert "Уровень кузницы: 10" in text
    assert "Уровень кузницы: 11" in text
    assert "Монеты считаются безлимитными" in text
    assert "исходный уровень не выше 22" in text


def test_maximum_war_points_returns_to_war_menu(monkeypatch):
    user = UserData(user_id=42, username="tester")
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB(user))
    bot = FakeBot()

    public_war_points(make_callback(data="war"), bot)

    text = bot.edited[0][0]
    assert "<b>Итого по активностям</b>" in text
    assert "Всего:" in text
    assert callback_data(bot.edited[0][3]) == ["war_menu"]


def test_maximum_war_points_excludes_accounts_stale_for_more_than_three_days(
    monkeypatch,
):
    current = UserData(user_id=42, username="current", hammers=300)
    boundary = UserData(user_id=43, username="boundary", hammers=200)
    stale = UserData(user_id=44, username="stale", hammers=500)
    current.mark_updated("hammers", date(2026, 8, 14))
    boundary.mark_updated("hammers", date(2026, 8, 11))
    stale.mark_updated("hammers", date(2026, 8, 10))
    users = [current, boundary, stale]
    monkeypatch.setattr(
        "tg.war.get_user_data_db",
        lambda: SimpleNamespace(get_users=lambda: users),
    )
    monkeypatch.setattr(
        "tg.war.public.now",
        lambda: datetime(2026, 8, 14),
    )
    bot = FakeBot()

    public_war_points(make_callback(data="war"), bot)

    expected = WarPointsCalculator().calculate(
        [current, boundary],
        WAR_STAGES,
    )
    text = bot.edited[0][0]
    assert f"Всего: <b>{format_points(expected.total)}</b>" in text
    assert "Учтено аккаунтов: <b>2</b>" in text
    assert (
        "Не учтено (ресурсы не обновлялись более 3 дней): <b>1</b>"
        in text
    )


def test_personal_war_calculator_prompts_when_data_is_missing(monkeypatch):
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: FakeUserDataDB())
    bot = FakeBot()

    personal_war_points(make_callback(), bot)

    text, _, _, markup = bot.edited[0]
    assert "заполните свои ресурсы" in text
    assert callback_data(markup) == [
        "accounts/war_calculator",
        "resources",
        "technologies",
        "pets",
        "war_menu",
    ]
