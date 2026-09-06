from html import unescape
from pathlib import Path
import re

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import GameAccount, UserData
from tg.user_data import (
    change_hatch_batch_count,
    hatch_batches_menu,
    max_egg_level_menu,
    pets_menu,
    save_max_egg_level,
)
from tg.user_data.pets import confirm_max_egg_level


def make_callback(data: str) -> CallbackQuery:
    user = User(42, False, "Tester", username="tester")
    chat = Chat(42, "private")
    message = Message(1, user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def callback_data(markup):
    if isinstance(markup, str):
        return re.findall(r'<tg-button[^>]+data="([^"]+)"', markup)
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
    ]


def button_texts(html):
    return [
        unescape(text)
        for text in re.findall(r"<tg-button\s[^>]*>(.*?)</tg-button>", html)
    ]


class FakeBot:
    def __init__(self):
        self.edited = []
        self.deleted_states = []
        self.answers = []

    def edit_message_text(
        self,
        text=None,
        chat_id=None,
        message_id=None,
        reply_markup=None,
        rich_message=None,
    ):
        content = rich_message.html if rich_message is not None else text
        self.edited.append((content, chat_id, message_id, reply_markup))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    def get_chat_member(self, group_id, user_id):
        return type("Member", (), {"status": "member"})()


class FakeUserDataDB:
    def __init__(self, user=None):
        self.user = user or UserData(user_id=42, username="tester")
        self.account = GameAccount(
            account_id=1,
            user_id=42,
            username="tester",
            tag="Main",
            is_active=True,
            clan_id=-100123,
            clan_title="Test clan",
        )

    def get_accounts(self, _user_id):
        return [self.account]

    def get_active_account(self, _user_id):
        return self.account

    def update_username(self, _user_id, username):
        self.user.username.value = username

    def get_assigned_user(self, _user_id):
        return self.user

    def set_value(self, _user_id, _username, field_name, value, **_kwargs):
        self.user.set_value(field_name, value)
        return self.user

    def set_values(self, _user_id, _username, values, **_kwargs):
        for field_name, value in values.items():
            self.user.set_value(field_name, value)
        return self.user


def configure(monkeypatch, user=None):
    database = FakeUserDataDB(user)
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    return database


def test_pets_menu_shows_current_settings_and_edit_actions(monkeypatch):
    configure(monkeypatch)
    bot = FakeBot()

    pets_menu(make_callback("pets"), bot)

    text, _, _, markup = bot.edited[0]
    assert "<h2>Настройки питомцев</h2>" in text
    assert "Яиц в одном пакете: <b>4</b>" in text
    assert "Максимальный уровень: <b>Мифическое</b>" in text
    assert "Пакетов в день: <b>2</b>" in text
    assert callback_data(text) == [
        "user_data/edit/eggs_per_hatch_batch",
        "pets/max_level",
        "pets/batches",
        "accounts/pets",
        "home",
    ]
    assert markup is None


def test_max_egg_level_is_selected_by_compact_colored_names(monkeypatch):
    configure(monkeypatch)
    bot = FakeBot()

    max_egg_level_menu(make_callback("pets/max_level"), bot)

    text = bot.edited[0][0]
    labels = button_texts(text)
    assert labels[:6] == [
        "🟣 Мифическое ✓",
        "🔴 Максимальное",
        "🟡 Легендарное",
        "🟢 Эпическое",
        "🔵 Редкое",
        "⚪ Обычное",
    ]


def test_lowering_max_level_warns_before_clearing_daily_batches(monkeypatch):
    database = configure(
        monkeypatch,
        UserData(
            user_id=42,
            username="tester",
            hatch_batches_ultimate=3,
            hatch_batches_mythic=2,
        ),
    )
    bot = FakeBot()

    save_max_egg_level(make_callback("pets/max_level/4"), bot)

    assert database.user.max_egg_level.value == 6
    assert database.user.hatch_batches_ultimate.value == 3
    assert database.user.hatch_batches_mythic.value == 2
    text, _, _, markup = bot.edited[-1]
    assert "Будут обнулены" in text
    assert "Мифическое <i>(Mythic)</i>: <b>2 пакета</b>" in text
    assert "Максимальное <i>(Ultimate)</i>: <b>3 пакета</b>" in text
    assert callback_data(text) == [
        "pets/max_level/confirm/4",
        "pets/max_level",
    ]
    assert markup is None


def test_confirming_lower_max_level_clears_unavailable_daily_batches(
    monkeypatch,
):
    database = configure(
        monkeypatch,
        UserData(
            user_id=42,
            username="tester",
            hatch_batches_ultimate=3,
            hatch_batches_mythic=2,
        ),
    )
    bot = FakeBot()

    confirm_max_egg_level(make_callback("pets/max_level/confirm/4"), bot)

    assert database.user.max_egg_level.value == 4
    assert database.user.hatch_batches_ultimate.value == 0
    assert database.user.hatch_batches_mythic.value == 0
    assert "Максимальный уровень: <b>Легендарное</b>" in bot.edited[-1][0]


def test_lowering_max_level_without_batch_data_saves_immediately(monkeypatch):
    database = configure(
        monkeypatch,
        UserData(
            user_id=42,
            username="tester",
            hatch_batches_ultimate=0,
            hatch_batches_mythic=0,
        ),
    )
    bot = FakeBot()

    save_max_egg_level(make_callback("pets/max_level/4"), bot)

    assert database.user.max_egg_level.value == 4
    assert "Максимальный уровень: <b>Легендарное</b>" in bot.edited[-1][0]
    assert "Будут обнулены" not in bot.edited[-1][0]


def test_daily_batch_editor_changes_each_level_independently(monkeypatch):
    database = configure(monkeypatch)
    bot = FakeBot()
    updates = []
    monkeypatch.setattr(
        "tg.user_data.pets.record_resource_update",
        lambda category, field: updates.append((category, field)),
    )

    hatch_batches_menu(make_callback("pets/batches"), bot)
    assert "pets/batches/6/plus" in callback_data(bot.edited[-1][0])
    assert "pets/batches/5/minus" in callback_data(bot.edited[-1][0])

    change_hatch_batch_count(make_callback("pets/batches/6/plus"), bot)
    change_hatch_batch_count(make_callback("pets/batches/5/minus"), bot)

    assert database.user.hatch_batches_mythic.value == 2
    assert database.user.hatch_batches_ultimate.value == 0
    assert updates == [
        ("pets", "hatch_batches_mythic"),
        ("pets", "hatch_batches_ultimate"),
    ]
    assert "Всего в день: <b>2</b>" in bot.edited[-1][0]
