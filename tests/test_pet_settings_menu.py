from pathlib import Path

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
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
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
    ]


class FakeBot:
    def __init__(self):
        self.edited = []
        self.deleted_states = []
        self.answers = []

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edited.append((text, chat_id, message_id, reply_markup))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))


class FakeUserDataDB:
    def __init__(self, user=None):
        self.user = user or UserData(user_id=42, username="tester")

    def get_or_create(self, _user_id, _username, _tag=None):
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
    monkeypatch.setattr("tg.user_data._get_group_tag", lambda *_: None)
    return database


def test_pets_menu_shows_current_settings_and_edit_actions(monkeypatch):
    configure(monkeypatch)
    bot = FakeBot()

    pets_menu(make_callback("pets"), bot)

    text, _, _, markup = bot.edited[0]
    assert "<b>Питомцы</b>" in text
    assert "Яиц в одном пакете: <b>4</b>" in text
    assert "🟣 Mythic / Мифическое" in text
    assert "🔴 Ultimate / Максимальное" in text
    assert "Пакетов в день: <b>2</b>" in text
    assert callback_data(markup) == [
        "accounts/pets",
        "user_data/edit/eggs_per_hatch_batch",
        "pets/max_level",
        "pets/batches",
        "home",
    ]


def test_max_egg_level_is_selected_by_bilingual_colored_names(monkeypatch):
    configure(monkeypatch)
    bot = FakeBot()

    max_egg_level_menu(make_callback("pets/max_level"), bot)

    markup = bot.edited[0][3]
    labels = [button.text for row in markup.keyboard for button in row]
    assert labels[:6] == [
        "🟣 Mythic / Мифическое ✓",
        "🔴 Ultimate / Максимальное",
        "🟡 Legendary / Легендарное",
        "🟢 Epic / Эпическое",
        "🔵 Rare / Редкое",
        "⚪ Common / Обычное",
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
    assert "Mythic / Мифическое: <b>2 пакета</b>" in text
    assert "Ultimate / Максимальное: <b>3 пакета</b>" in text
    assert callback_data(markup) == [
        "pets/max_level/confirm/4",
        "pets/max_level",
    ]


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
    assert "Legendary / Легендарное" in bot.edited[-1][0]


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
    assert "Legendary / Легендарное" in bot.edited[-1][0]
    assert "Будут обнулены" not in bot.edited[-1][0]


def test_daily_batch_editor_changes_each_level_independently(monkeypatch):
    database = configure(monkeypatch)
    bot = FakeBot()

    hatch_batches_menu(make_callback("pets/batches"), bot)
    assert "pets/batches/6/plus" in callback_data(bot.edited[-1][3])
    assert "pets/batches/5/minus" in callback_data(bot.edited[-1][3])

    change_hatch_batch_count(make_callback("pets/batches/6/plus"), bot)
    change_hatch_batch_count(make_callback("pets/batches/5/minus"), bot)

    assert database.user.hatch_batches_mythic.value == 2
    assert database.user.hatch_batches_ultimate.value == 0
    assert "Всего в день: <b>2</b>" in bot.edited[-1][0]
