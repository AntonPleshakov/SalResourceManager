from pathlib import Path

from telebot.types import CallbackQuery, Chat, Message, User

from config import config
from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))
config._config.set(config._MODE, "TOKEN", "123456:test-token")

from main import AlwaysAnswerCallbackQueryMiddleware


def test_callback_middleware_pre_process_is_a_noop():
    user = User(42, False, "Tester", username="tester")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    callback_query = CallbackQuery(
        "callback-1", user, "admins", "", None, message
    )

    result = AlwaysAnswerCallbackQueryMiddleware().pre_process(callback_query, {})

    assert result is None
