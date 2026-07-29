from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from tg import admins
from tg.navigation import home
from tg.utils import Button, empty_filter, get_ids


def resources_menu(callback_query: CallbackQuery, bot: TeleBot):
    _, chat_id, message_id = get_ids(callback_query)
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(Button("Назад в меню", "home").inline())
    bot.edit_message_text(
        "Раздел учета ресурсов подготовлен. Здесь появятся операции, остатки и отчеты.",
        chat_id,
        message_id,
        reply_markup=keyboard,
    )


def register_handlers(bot: TeleBot):
    bot.register_message_handler(
        home, commands=["start"], chat_types=["private"], pass_bot=True, is_admin=True
    )
    bot.register_callback_query_handler(
        home, func=empty_filter, button="home", is_private=True, pass_bot=True
    )
    bot.register_callback_query_handler(
        resources_menu,
        func=empty_filter,
        button="resources",
        is_private=True,
        pass_bot=True,
    )
    admins.register_handlers(bot)
