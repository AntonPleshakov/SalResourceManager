from pathlib import Path
from types import SimpleNamespace

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UserData
from tg.onboarding import show_new_user_welcome


def make_callback() -> CallbackQuery:
    user = User(42, False, "Tester", username="tester")
    chat = Chat(42, "private")
    message = Message(1, user, 0, chat, "text", {"text": "menu"}, None)
    return CallbackQuery("callback-1", user, "home", "", None, message)


class FakeBot:
    def __init__(self):
        self.edited = []

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edited.append((text, chat_id, message_id, reply_markup))


def callback_data(markup):
    return [button.callback_data for row in markup.keyboard for button in row]


def active_user(
    *, is_new_user: bool, group_tag_found: bool | None, tag: str
):
    return SimpleNamespace(
        user=UserData(user_id=42, username="tester", tag=tag),
        is_new_user=is_new_user,
        group_tag_found=group_tag_found,
    )


def test_new_user_sees_account_created_from_group_tag(monkeypatch):
    monkeypatch.setattr(
        "tg.onboarding.ensure_active_user",
        lambda *_: active_user(
            is_new_user=True, group_tag_found=True, tag="Лидер"
        ),
    )
    bot = FakeBot()

    assert show_new_user_welcome(make_callback(), bot) is True

    text, _, _, markup = bot.edited[0]
    assert "Добро пожаловать" in text
    assert "По вашему тегу в группе создан игровой аккаунт <b>Лидер</b>" in text
    assert callback_data(markup) == ["home"]


def test_new_user_is_asked_to_rename_account_when_group_tag_is_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        "tg.onboarding.ensure_active_user",
        lambda *_: active_user(
            is_new_user=True, group_tag_found=False, tag="tester"
        ),
    )
    bot = FakeBot()

    assert show_new_user_welcome(make_callback(), bot) is True

    text, _, _, markup = bot.edited[0]
    assert "Не удалось получить ваш тег из группы" in text
    assert "временно назван <b>tester</b>" in text
    assert "Переименуйте его" in text
    assert callback_data(markup) == ["accounts/rename", "home"]


def test_existing_account_does_not_trigger_onboarding(monkeypatch):
    monkeypatch.setattr(
        "tg.onboarding.ensure_active_user",
        lambda *_: active_user(
            is_new_user=False, group_tag_found=None, tag="Лидер"
        ),
    )
    bot = FakeBot()

    assert show_new_user_welcome(make_callback(), bot) is False
    assert bot.edited == []
