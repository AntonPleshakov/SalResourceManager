from telebot import TeleBot


def serve_polling(bot: TeleBot) -> None:
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
