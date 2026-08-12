from pathlib import Path

from telebot.types import CallbackQuery, Chat, Message, User

from config import config
from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))
config._config.set(config._MODE, "TOKEN", "123456:test-token")

from main import AlwaysAnswerCallbackQueryMiddleware, UserFacingErrorMiddleware


def make_message() -> Message:
    user = User(42, False, "Tester", username="tester")
    return Message(1, user, 0, Chat(42, "private"), "text", {}, None)


class FakeBot:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, chat_id, text, reply_markup=None):
        if self.fail:
            raise RuntimeError("bot was blocked")
        self.sent.append((chat_id, text, reply_markup))


def test_callback_middleware_pre_process_is_a_noop():
    message = make_message()
    user = message.from_user
    callback_query = CallbackQuery(
        "callback-1", user, "admins", "", None, message
    )

    result = AlwaysAnswerCallbackQueryMiddleware().pre_process(callback_query, {})

    assert result is None


def test_user_is_notified_about_unexpected_handler_error():
    bot = FakeBot()
    middleware = UserFacingErrorMiddleware(bot)

    middleware.post_process(make_message(), {}, RuntimeError("database failed"))

    assert len(bot.sent) == 1
    chat_id, text, markup = bot.sent[0]
    assert chat_id == 42
    assert "неожиданной ошибки" in text
    assert "Вернитесь в меню и попробуйте снова" in text
    assert "database failed" not in text
    assert markup.keyboard[0][0].text == "Вернуться в меню"
    assert markup.keyboard[0][0].callback_data == "home"


def test_callback_error_is_reported_in_its_private_chat():
    bot = FakeBot()
    message = make_message()
    callback_query = CallbackQuery(
        "callback-1",
        message.from_user,
        "resources",
        "",
        None,
        message,
    )

    UserFacingErrorMiddleware(bot).post_process(
        callback_query, {}, RuntimeError("database failed")
    )

    assert bot.sent[0][0] == 42
    assert bot.sent[0][2].keyboard[0][0].callback_data == "home"


def test_user_is_not_notified_when_handler_succeeds():
    bot = FakeBot()

    UserFacingErrorMiddleware(bot).post_process(make_message(), {}, None)

    assert bot.sent == []


def test_notification_failure_does_not_raise_another_error():
    middleware = UserFacingErrorMiddleware(FakeBot(fail=True))

    middleware.post_process(make_message(), {}, RuntimeError("database failed"))
