"""Review offline screenshot readings before updating an account."""

from functools import wraps
from html import escape
import threading
from uuid import uuid4

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.handler_backends import State, StatesGroup
from telebot.types import CallbackQuery, Message

from logger.app_logger import logger
from resources.screenshot_input import (
    MAX_IMAGE_BYTES, SCREENSHOT_FIELDS, ScreenshotError, ocr_available,
    recognize_screenshot, validate_value,
)
from resources.user_data import EDITABLE_FIELDS, parse_editable_field_value
import tg.user_data as user_data
from tg.handlers import HandlerRegistry
from tg.metrics import record_resource_update
from tg.message_updates import is_message_not_modified
from tg.rich import (
    account_context, back_button, button_row, callback_button,
    deliver_rich_message, details, edit_rich_message, heading,
    input_rich_message, notice as rich_notice,
)
from tg.user_data.common import get_active_user_or_prompt, get_current_accounts, localized_field_title
from tg.user_data.editing_common import VALUE_EDIT_SECTIONS
from tg.utils import get_ids, get_username


class ScreenshotStates(StatesGroup):
    review = State()


_LOCKS = tuple(threading.RLock() for _ in range(64))
_KEY = "screenshot_import"


def _serialized(handler):
    @wraps(handler)
    def run(update, bot):
        with _LOCKS[get_ids(update)[0] % len(_LOCKS)]:
            return handler(update, bot)
    return run


def _load(update, bot, *, check_callback=True):
    user_id = get_ids(update)[0]
    if bot.get_state(user_id) != ScreenshotStates.review.name:
        return None
    with bot.retrieve_data(user_id) as data:
        session = data.get(_KEY)
        if not isinstance(session, dict):
            return None
        session = {**session, "values": dict(session.get("values", {}))}
    if check_callback and isinstance(update, CallbackQuery):
        if update.data.split("/")[1] != session["token"]:
            bot.answer_callback_query(update.id, "Это устаревший просмотр. Используйте последний.")
            return None
    return session


def _delete_input(message: Message, bot: TeleBot) -> None:
    _, chat_id, message_id = get_ids(message)
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException:
        logger.warning("Unable to delete screenshot input chat_id=%s message_id=%s", chat_id, message_id)


def _screenshot_notices(session):
    return "".join(
        rich_notice(f"Скриншот №{item['number']}: {escape(item['reason'])}")
        for item in session.get("screenshot_notices", [])
    )


def _add_screenshot_notice(session, reason):
    session["screenshot_notices"] = [
        *session.get("screenshot_notices", []),
        {"number": session["screenshot_count"], "reason": reason},
    ]


def _review_message(session, notice=""):
    token = session["token"]
    parts = [heading("Проверка скриншотов"), account_context(session["tag"])]
    if notice:
        parts.append(rich_notice(escape(notice)))
    editing = session.get("edit")
    if editing:
        parts.append(f"<p>Введите исправленное значение: <b>{escape(localized_field_title(EDITABLE_FIELDS[editing], session.get('user_id', 0)))}</b>.</p>")
    elif not session["values"]:
        parts.append("<p>Отправьте скриншоты игры по одному или альбомом.</p>")
    for name in SCREENSHOT_FIELDS:
        if name not in session["values"]:
            continue
        title = localized_field_title(EDITABLE_FIELDS[name], session.get('user_id', 0))
        value = session["values"][name]
        suffix = "%" if name.endswith(("chance", "cost")) else ""
        displayed = f"{value:,}{suffix}".replace(",", " ")
        parts.append(f"<p>{escape(title)}: <b>{displayed}</b></p>")
        parts.append(button_row((
            callback_button("✏️ Изменить", f"screenshot/{token}/edit/{name}"),
            callback_button("✖️ Исключить", f"screenshot/{token}/drop/{name}"),
        )))
    if session["values"] and not editing:
        parts.append("<p>Проверьте значения перед сохранением. Можно отправить ещё скриншоты.</p>")
        parts.append(button_row((callback_button("✅ Сохранить найденное", f"screenshot/{token}/save", style="primary"),)))
    if session.get("screenshot_count"):
        parts.append(f"<p>Получено скриншотов: {session['screenshot_count']}.</p>")
    parts.append(_screenshot_notices(session))
    parts.append(details("Как работает распознавание",
        "<p>Фото и файлы JPEG/PNG/WebP до 10 МБ. Значения накапливаются; "
        "новый скриншот заменяет предыдущее чтение того же показателя. "
        "Скриншоты нумеруются в порядке загрузки.</p>"
        "<p>До подтверждения ничего не сохраняется. Отсутствующие показатели не меняются.</p>"
        "<p>Технологии поддерживают русский, английский и немецкий. Для других языков используйте ручной ввод.</p>"))
    parts.append(back_button("✖️ Отмена", "home"))
    return input_rich_message(parts)


def _edit_view(update, bot, session, rich_message):
    try:
        edit_rich_message(bot, get_ids(update)[1], session["prompt_message_id"], rich_message)
    except ApiTelegramException as error:
        if not is_message_not_modified(error):
            raise


def _update_review(update, bot, session, notice=""):
    current = _load(update, bot, check_callback=False)
    if current is None or current["token"] != session["token"]:
        return
    _edit_view(update, bot, session, _review_message(session, notice))


def _show(update, bot, session, notice=""):
    session.update(token=uuid4().hex[:12], edit=None)
    bot.add_data(get_ids(update)[0], **{_KEY: session})
    _update_review(update, bot, session, notice)


def _record_upload_error(update, bot, session, reason):
    current = _load(update, bot, check_callback=False)
    if current is None or current["token"] != session["token"]:
        return
    _add_screenshot_notice(session, reason)
    bot.add_data(get_ids(update)[0], **{_KEY: session})
    _update_review(update, bot, session)


def _finish_message(session, notice):
    return input_rich_message((
        heading("Скриншоты"), account_context(session["tag"]), rich_notice(escape(notice)),
        _screenshot_notices(session),
        button_row((callback_button("Ресурсы", "resources"), callback_button("Технологии", "technologies"))),
        back_button("🏠 Главное меню", "home"),
    ))


def _account(update, bot, session):
    current = get_active_user_or_prompt(update, bot)
    if current is None:
        bot.delete_state(get_ids(update)[0])
        return None
    database = user_data.get_user_data_db()
    assigned = database.get_assigned_user(get_ids(update)[0], session["account_id"])
    error = ""
    if assigned is None or current.account_id.value != session["account_id"]:
        error = "Аккаунт изменился. Начните загрузку скриншотов заново."
    elif not any(account.account_id == session["account_id"] and account.clan_id == session["clan_id"]
                 for account in database.get_accounts(get_ids(update)[0])):
        error = "Клан аккаунта изменился. Начните загрузку заново."
    if error:
        bot.delete_state(get_ids(update)[0])
        _edit_view(update, bot, session, _finish_message(session, error))
        return None
    return current


@_serialized
def start_screenshot(update: CallbackQuery, bot: TeleBot) -> None:
    if not ocr_available():
        logger.warning("Screenshot input unavailable: Tesseract executable not found")
        deliver_rich_message(update, bot, input_rich_message((
            heading("Скриншоты"), rich_notice("Распознавание пока не настроено администратором: Tesseract не найден."),
            back_button("Вернуться к ресурсам", "resources"),
        )))
        return
    parts = update.data.split("/")
    if len(parts) == 3:
        account_id = int(parts[2])
        accounts = get_current_accounts(update, bot)
        if accounts is None:
            return
        selected = next((account for account in accounts if account.account_id == account_id and account.clan_id is not None), None)
        if selected is None:
            deliver_rich_message(update, bot, input_rich_message((
                heading("Скриншоты"), rich_notice("Аккаунт недоступен. Выберите аккаунт заново."),
                back_button("Выбрать аккаунт", "accounts/resources"),
            )))
            return
        user_data.get_user_data_db().select_account(get_ids(update)[0], account_id)
    current = get_active_user_or_prompt(update, bot)
    if current is None:
        return
    account = next(account for account in user_data.get_user_data_db().get_accounts(
        get_ids(update)[0]) if account.account_id == current.account_id.value)
    bot.delete_state(get_ids(update)[0])
    bot.set_state(get_ids(update)[0], ScreenshotStates.review)
    _show(update, bot, {"user_id": get_ids(update)[0], "account_id": current.account_id.value,
                       "clan_id": account.clan_id, "tag": str(current.tag.value),
                       "values": {}, "prompt_message_id": update.message.id})
    bot.answer_callback_query(update.id)


@_serialized
def receive_screenshot(message: Message, bot: TeleBot) -> None:
    session = _load(message, bot)
    if session is None or _account(message, bot, session) is None:
        return
    session["screenshot_count"] = session.get("screenshot_count", 0) + 1
    bot.add_data(get_ids(message)[0], **{_KEY: session})
    file = message.photo[-1] if message.content_type == "photo" else message.document
    if file.file_size and file.file_size > MAX_IMAGE_BYTES:
        _record_upload_error(message, bot, session, "Превышен размер вложения (10 МБ).")
        return
    try:
        telegram_file = bot.get_file(file.file_id)
        if telegram_file.file_size and telegram_file.file_size > MAX_IMAGE_BYTES:
            raise ScreenshotError("Отправьте изображение размером до 10 МБ.")
        image = bot.download_file(telegram_file.file_path)
        _delete_input(message, bot)
        values = recognize_screenshot(image)
    except ScreenshotError as error:
        _record_upload_error(message, bot, session, str(error))
        return
    except Exception as error:
        # Telegram exceptions may contain file URLs/tokens: never log their text.
        logger.warning("Screenshot download/recognition failed user_id=%s type=%s",
                       message.from_user.id, type(error).__name__)
        _record_upload_error(message, bot, session, "Ошибка обработки вложения. Попробуйте загрузить повторно.")
        return
    latest = _load(message, bot)
    if latest is None or latest["token"] != session["token"]:
        return
    session["values"].update(values)
    if not values:
        _add_screenshot_notice(session, "подходящие значения не найдены.")
    _show(message, bot, session)


@_serialized
def edit_reading(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None:
        return
    name = update.data.split("/")[-1]
    if name not in session["values"]:
        return
    session["edit"] = name
    bot.add_data(get_ids(update)[0], **{_KEY: session})
    _update_review(update, bot, session)
    bot.answer_callback_query(update.id)


@_serialized
def correct_reading(message: Message, bot: TeleBot) -> None:
    session = _load(message, bot)
    if session is None:
        return
    _delete_input(message, bot)
    name = session.get("edit")
    if name not in session["values"]:
        _update_review(message, bot, session, "Отправьте скриншот или выберите «Изменить» возле значения.")
        return
    try:
        value = validate_value(name, parse_editable_field_value(name, message.text))
    except ValueError as error:
        _update_review(message, bot, session, str(error))
        return
    session["values"][name] = value
    _show(message, bot, session, "Значение исправлено; ещё не сохранено.")


@_serialized
def drop_reading(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None:
        return
    session["values"].pop(update.data.split("/")[-1], None)
    _show(update, bot, session, "Показатель исключён из сохранения.")
    bot.answer_callback_query(update.id)


@_serialized
def save_readings(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None or not session["values"]:
        return
    if session.get("edit"):
        _update_review(update, bot, session, "Сначала введите исправленное значение.")
        return
    if _account(update, bot, session) is None:
        return
    values = {name: validate_value(name, value) for name, value in session["values"].items()}
    try:
        user_data.get_user_data_db().set_values(
            get_ids(update)[0], get_username(update), values, account_id=session["account_id"],
        )
    except ValueError:
        _update_review(update, bot, session, "Не удалось сохранить значения. Откройте раздел заново.")
        return
    bot.delete_state(get_ids(update)[0])
    for name in values:
        record_resource_update(VALUE_EDIT_SECTIONS[name], name)
    _edit_view(update, bot, session, _finish_message(session, f"✅ Сохранено показателей: {len(values)}."))
    bot.answer_callback_query(update.id)


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.private_callback(start_screenshot, button=r"screenshot/start(?:/[0-9]+)?")
    handlers.private_message(receive_screenshot, content_types=["photo", "document"], state=ScreenshotStates.review)
    handlers.private_message(correct_reading, content_types=["text"], state=ScreenshotStates.review)
    handlers.private_callback(save_readings, button=r"screenshot/[a-f0-9]{12}/save", state=ScreenshotStates.review)
    names = "(" + "|".join(SCREENSHOT_FIELDS) + ")"
    handlers.private_callback(edit_reading, button=rf"screenshot/[a-f0-9]{{12}}/edit/{names}", state=ScreenshotStates.review)
    handlers.private_callback(drop_reading, button=rf"screenshot/[a-f0-9]{{12}}/drop/{names}", state=ScreenshotStates.review)
