from telebot import TeleBot

from tg.update_types import ALLOWED_UPDATES


def serve_polling(bot: TeleBot) -> None:
    bot.remove_webhook()
    bot.infinity_polling(
        skip_pending=True,
        allowed_updates=list(ALLOWED_UPDATES),
    )
