from telebot.types import CallbackQuery, Message


Update = Message | CallbackQuery


def event_type(update: Update) -> str:
    return "callback_query" if isinstance(update, CallbackQuery) else "message"


def chat_type(update: Update) -> str:
    if isinstance(update, CallbackQuery):
        return "unknown" if update.message is None else update.message.chat.type
    return update.chat.type


def log_context(update: Update) -> tuple[object, object, object]:
    user_id = None if update.from_user is None else update.from_user.id
    if isinstance(update, CallbackQuery):
        chat_id = None if update.message is None else update.message.chat.id
        return user_id, chat_id, update.id
    return user_id, update.chat.id, update.message_id
