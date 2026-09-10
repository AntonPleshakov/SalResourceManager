from unittest.mock import Mock, call

from tg.polling import serve_polling


def test_serve_polling_removes_webhook_before_polling():
    bot = Mock()

    serve_polling(bot)

    assert bot.mock_calls == [
        call.remove_webhook(),
        call.infinity_polling(
            skip_pending=True,
            allowed_updates=["message", "callback_query", "chat_member"],
        ),
    ]
