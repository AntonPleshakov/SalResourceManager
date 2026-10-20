"""Review offline screenshot readings before updating an account."""

from functools import partial, wraps
from html import escape
from pathlib import Path
import threading
from uuid import uuid4

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.handler_backends import SkipHandler, State, StatesGroup
from telebot.types import CallbackQuery, Message

from logger.app_logger import logger
from resources.screenshot_input import (
    MAX_IMAGE_BYTES, SCREENSHOT_FIELDS, ScreenshotError, ocr_available,
    recognize_screenshot, validate_value,
)
from resources.user_data import EDITABLE_FIELDS, parse_editable_field_value
from resources.screenshot_storage import delete_screenshot, save_screenshot
import tg.user_data as user_data
from tg.handlers import HandlerRegistry
from tg.metrics import observe_screenshot_stage, record_resource_update, record_screenshot_processed
from tg.message_updates import is_message_not_modified
from tg.middleware import NoOpPostProcessMiddleware
from tg.user_data.screenshot_jobs import ScreenshotJob, ScreenshotWorker
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
_WAIT_MESSAGE = "Дождитесь окончания распознавания."


def _answer_callback(bot, update, text=None):
    try:
        bot.answer_callback_query(update.id, text)
    except ApiTelegramException as error:
        description = error.description.lower()
        if "query is too old" not in description and "query id is invalid" not in description:
            raise
        logger.warning("Screenshot callback expired user_id=%s", update.from_user.id)


def _worker(bot):
    worker = getattr(bot, "_screenshot_worker", None)
    if worker is None:
        worker = ScreenshotWorker(bot.worker_pool.put)
        bot._screenshot_worker = worker
    return worker


def _uploads(bot):
    if not hasattr(bot, "_screenshot_uploads"):
        bot._screenshot_uploads = {}
    return bot._screenshot_uploads


def _remove_progress(bot, session_id):
    progress = _uploads(bot).pop(session_id, None)
    if progress is None or progress.get("message_id") is None:
        return
    try:
        bot.delete_message(progress["chat_id"], progress["message_id"])
    except Exception as error:
        logger.warning("Unable to delete screenshot progress user_id=%s type=%s",
                       progress["user_id"], type(error).__name__)


def _cancel_upload(bot, session_id, *, keep_message=False):
    worker = getattr(bot, "_screenshot_worker", None)
    if worker is not None:
        worker.cancel(session_id)
    if keep_message:
        _uploads(bot).pop(session_id, None)
    else:
        _remove_progress(bot, session_id)


def stop_screenshot_worker(bot):
    worker = getattr(bot, "_screenshot_worker", None)
    if worker is not None:
        worker.stop()
    for session_id in tuple(_uploads(bot)):
        _remove_progress(bot, session_id)


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
        session = {**session, "values": dict(session.get("values", {})),
                   "sources": dict(session.get("sources", {})),
                   "input_sources": dict(session.get("input_sources", {}))}
    if check_callback and isinstance(update, CallbackQuery):
        if update.data.split("/")[1] != session["token"]:
            _answer_callback(bot, update, "Это устаревший просмотр. Используйте последний.")
            return None
    return session


def _delete_input(message: Message, bot: TeleBot) -> None:
    _, chat_id, message_id = get_ids(message)
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException:
        logger.warning("Unable to delete screenshot input chat_id=%s message_id=%s", chat_id, message_id)


def _delete_screenshot_inputs(bot, session):
    message_ids = session.get("screenshot_message_ids", [])
    # deleteMessages skips inputs already removed by the OCR worker.
    for offset in range(0, len(message_ids), 100):
        try:
            bot.delete_messages(session["user_id"], message_ids[offset:offset + 100])
        except Exception as error:
            logger.warning("Unable to delete cancelled screenshot inputs user_id=%s type=%s",
                           session["user_id"], type(error).__name__)


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
    cancel = f"screenshot/{session['session_id'][:12]}/cancel"
    if session.get("pending"):
        parts.append(button_row((callback_button("✖️ Отмена", cancel),)))
    else:
        parts.append(back_button("✖️ Отмена", cancel))
    return input_rich_message(parts)


def _edit_view(update, bot, session, rich_message):
    try:
        if session["prompt_message_id"] is None:
            session["prompt_message_id"] = bot.send_rich_message(get_ids(update)[1], rich_message).message_id
            current = _load(update, bot, check_callback=False)
            if current is not None and current["session_id"] == session["session_id"]:
                bot.add_data(get_ids(update)[0], **{_KEY: session})
        else:
            edit_rich_message(bot, get_ids(update)[1], session["prompt_message_id"], rich_message)
    except ApiTelegramException as error:
        if not is_message_not_modified(error):
            raise


def _progress(bot, session, notice=""):
    session_id = session["session_id"]
    progress = _uploads(bot).get(session_id)
    if progress is None:
        progress = {"chat_id": session["user_id"], "user_id": session["user_id"], "message_id": None}
        _uploads(bot)[session_id] = progress
        previous_message_id = session["prompt_message_id"]
        session["prompt_message_id"] = None
        bot.add_data(session["user_id"], **{_KEY: session})
        try:
            if previous_message_id is not None:
                bot.delete_message(progress["chat_id"], previous_message_id)
        except Exception as error:
            logger.warning("Unable to delete screenshot prompt user_id=%s type=%s",
                           session["user_id"], type(error).__name__)
    parts = [heading("Распознавание скриншотов"),
             f"<p>Обработано {session['processed']} из {session['upload_total']}.</p>"]
    if notice:
        parts.append(rich_notice(escape(notice)))
    parts.append(button_row((callback_button("✖️ Отмена", f"screenshot/{session_id[:12]}/cancel"),)))
    rich_message = input_rich_message(parts)
    try:
        if progress["message_id"] is None:
            progress["message_id"] = bot.send_rich_message(progress["chat_id"], rich_message).message_id
            session["prompt_message_id"] = progress["message_id"]
            bot.add_data(session["user_id"], **{_KEY: session})
        else:
            edit_rich_message(bot, progress["chat_id"], progress["message_id"], rich_message)
    except Exception as error:
        if not (isinstance(error, ApiTelegramException) and is_message_not_modified(error)):
            logger.warning("Unable to update screenshot progress user_id=%s type=%s",
                           session["user_id"], type(error).__name__)


def _update_review(update, bot, session, notice=""):
    current = _load(update, bot, check_callback=False)
    if current is None or current["token"] != session["token"]:
        return
    if session.get("pending"):
        _progress(bot, session, notice)
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


def _delete_stored_screenshot(user_id, path):
    try:
        delete_screenshot(path)
    except (OSError, ValueError):
        logger.warning("Screenshot retained user_id=%s screenshot_path=%s reason=%s",
                       user_id, path, "delete_failed")


def _discard_screenshot(user_id, result, error):
    if result is not None and result[1] is not None:
        _delete_stored_screenshot(user_id, result[1])


def _log_retained_screenshot(session, path, reason):
    readings = session.get("screenshot_readings", {}).get(path)
    if (not readings or path in session.get("edited_screenshots", [])
            or path in session.get("warned_screenshots", [])):
        # OCR failures, empty results and corrections already include the file in WARNING.
        return
    if Path(path).is_file():
        logger.warning("Screenshot retained user_id=%s screenshot_path=%s reason=%s",
                       session["user_id"], path, reason)
        session["warned_screenshots"] = [*session.get("warned_screenshots", []), path]


def _complete_screenshot(message, bot, session_id, number, result, error):
    session = _load(message, bot)
    if session is None or session.get("session_id") != session_id:
        _cancel_upload(bot, session_id)
        _discard_screenshot(message.from_user.id, result, error)
        return
    if _account(message, bot, session) is None:
        _cancel_upload(bot, session_id, keep_message=True)
        _discard_screenshot(message.from_user.id, result, error)
        return
    if error is not None:
        result = ({}, None, "Ошибка обработки вложения. Попробуйте загрузить повторно.", False)
    values, screenshot_path, notice, recognized = result
    if screenshot_path is not None:
        session["screenshot_readings"] = {
            **session.get("screenshot_readings", {}), screenshot_path: dict(values),
        }
    session["pending"] -= 1
    session["processed"] += 1
    for name in values:
        previous_path = session["sources"].get(name)
        if previous_path is not None:
            _log_retained_screenshot(session, previous_path, "replaced")
    session["values"].update(values)
    session["sources"].update({name: screenshot_path for name in values})
    session["input_sources"].update({name: "screenshot" for name in values})
    if notice:
        session["screenshot_notices"] = [
            *session.get("screenshot_notices", []), {"number": number, "reason": notice},
        ]
    bot.add_data(get_ids(message)[0], **{_KEY: session})
    if session["pending"]:
        _progress(bot, session)
        return
    _uploads(bot).pop(session_id, None)
    if recognized:
        _show(message, bot, session)
    else:
        _update_review(message, bot, session)


def _process_screenshot(message, bot):
    file = message.photo[-1] if message.content_type == "photo" else message.document
    screenshot_path = None
    try:
        with observe_screenshot_stage("download"):
            telegram_file = bot.get_file(file.file_id)
            if telegram_file.file_size and telegram_file.file_size > MAX_IMAGE_BYTES:
                raise ScreenshotError("Отправьте изображение размером до 10 МБ.")
            image = bot.download_file(telegram_file.file_path)
        screenshot_path = save_screenshot(image, telegram_file.file_path)
        _delete_input(message, bot)
        with observe_screenshot_stage("recognize"):
            values = recognize_screenshot(image)
    except ScreenshotError as error:
        if screenshot_path is not None:
            record_screenshot_processed("failed")
        logger.warning("Screenshot recognition failed user_id=%s screenshot_path=%s",
                       message.from_user.id, screenshot_path)
        return {}, screenshot_path, str(error), False
    except Exception as error:
        if screenshot_path is not None:
            record_screenshot_processed("failed")
        logger.warning("Screenshot download/recognition failed user_id=%s type=%s screenshot_path=%s",
                       message.from_user.id, type(error).__name__, screenshot_path)
        return {}, screenshot_path, "Ошибка обработки вложения. Попробуйте загрузить повторно.", False
    record_screenshot_processed("found" if values else "empty")
    if not values:
        logger.warning("No screenshot values found user_id=%s screenshot_path=%s",
                       message.from_user.id, screenshot_path)
    return values, screenshot_path, "" if values else "подходящие значения не найдены.", True


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
                       "values": {}, "prompt_message_id": update.message.id,
                       "session_id": uuid4().hex, "pending": 0})
    _answer_callback(bot, update)


@_serialized
def receive_screenshot(message: Message, bot: TeleBot) -> None:
    session = _load(message, bot)
    if session is None or _account(message, bot, session) is None:
        return
    session["screenshot_message_ids"] = list(dict.fromkeys([
        *session.get("screenshot_message_ids", []), message.id,
    ]))
    bot.add_data(get_ids(message)[0], **{_KEY: session})
    file = message.photo[-1] if message.content_type == "photo" else message.document
    if file.file_size and file.file_size > MAX_IMAGE_BYTES:
        session["screenshot_count"] = session.get("screenshot_count", 0) + 1
        bot.add_data(get_ids(message)[0], **{_KEY: session})
        _record_upload_error(message, bot, session, "Превышен размер вложения (10 МБ).")
        return
    number = session.get("screenshot_count", 0) + 1
    job = ScreenshotJob(
        get_ids(message)[0], session["session_id"],
        partial(_process_screenshot, message, bot),
        partial(_complete_screenshot, message, bot, session["session_id"], number),
        partial(_discard_screenshot, get_ids(message)[0]),
    )
    if not _worker(bot).submit(job):
        _update_review(message, bot, session, "Очередь распознавания заполнена. Отправьте скриншот позже.")
        return
    if not session.get("pending"):
        session.update(processed=0, upload_total=0)
    session["screenshot_count"] = number
    session["pending"] += 1
    session["upload_total"] += 1
    bot.add_data(get_ids(message)[0], **{_KEY: session})
    _progress(bot, session)


def _wait_for_screenshots(update, bot, session):
    if not session.get("pending"):
        return False
    if isinstance(update, CallbackQuery):
        _answer_callback(bot, update, _WAIT_MESSAGE)
    else:
        _update_review(update, bot, session, _WAIT_MESSAGE)
    return True


def cancel_screenshots(update, bot):
    from tg.navigation import home

    session = _load(update, bot, check_callback=False)
    if (session is not None and isinstance(update, CallbackQuery)
            and update.data != f"screenshot/{session['session_id'][:12]}/cancel"):
        _answer_callback(bot, update, "Это устаревший просмотр. Используйте последний.")
        return
    if session is not None:
        _cancel_upload(bot, session["session_id"], keep_message=True)
        for path in session.get("screenshot_readings", {}):
            _delete_stored_screenshot(session["user_id"], path)
        _delete_screenshot_inputs(bot, session)
        home(update, bot, edit_message_id=session["prompt_message_id"])
    else:
        home(update, bot)


@_serialized
def edit_reading(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None:
        return
    if _wait_for_screenshots(update, bot, session):
        return
    name = update.data.split("/")[-1]
    if name not in session["values"]:
        return
    session["edit"] = name
    bot.add_data(get_ids(update)[0], **{_KEY: session})
    _update_review(update, bot, session)
    _answer_callback(bot, update)


@_serialized
def correct_reading(message: Message, bot: TeleBot) -> None:
    session = _load(message, bot)
    if session is None:
        return
    if _wait_for_screenshots(message, bot, session):
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
    if value != session["values"][name]:
        session["input_sources"][name] = "manual"
        screenshot_path = session["sources"].get(name)
        if screenshot_path is not None:
            session["edited_screenshots"] = list(dict.fromkeys([
                *session.get("edited_screenshots", []), screenshot_path,
            ]))
        logger.warning(
            "Screenshot value corrected user_id=%s field=%s old_value=%s new_value=%s screenshot_path=%s",
            message.from_user.id, name, session["values"][name], value,
            session["sources"].get(name),
        )
    session["values"][name] = value
    _show(message, bot, session, "Значение исправлено; ещё не сохранено.")


@_serialized
def drop_reading(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None:
        return
    if _wait_for_screenshots(update, bot, session):
        return
    name = update.data.split("/")[-1]
    screenshot_path = session["sources"].get(name)
    if screenshot_path is not None:
        _log_retained_screenshot(session, screenshot_path, "excluded")
    session["values"].pop(name, None)
    session["sources"].pop(name, None)
    session["input_sources"].pop(name, None)
    _show(update, bot, session, "Показатель исключён из сохранения.")
    _answer_callback(bot, update)


def _log_retained_screenshots(session, reason):
    for path in session.get("screenshot_readings", {}):
        _log_retained_screenshot(session, path, reason)


def _cleanup_saved_screenshots(session, saved_values):
    for path, readings in session.get("screenshot_readings", {}).items():
        if path in session.get("edited_screenshots", []):
            reason = "edited"
        elif not readings:
            reason = "no_readings"
        elif any(name not in saved_values for name in readings):
            reason = "excluded"
        elif any(session["sources"].get(name) != path for name in readings):
            reason = "replaced"
        elif any(saved_values[name] != original or session["input_sources"].get(name) == "manual"
                 for name, original in readings.items()):
            reason = "edited"
        else:
            try:
                delete_screenshot(path)
                continue
            except (OSError, ValueError):
                reason = "delete_failed"
        _log_retained_screenshot(session, path, reason)


@_serialized
def save_readings(update: CallbackQuery, bot: TeleBot) -> None:
    session = _load(update, bot)
    if session is None:
        return
    if _wait_for_screenshots(update, bot, session) or not session["values"]:
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
        _log_retained_screenshots(session, "save_failed")
        _update_review(update, bot, session, "Не удалось сохранить значения. Откройте раздел заново.")
        return
    except Exception:
        _log_retained_screenshots(session, "save_failed")
        raise
    _cleanup_saved_screenshots(session, values)
    bot.delete_state(get_ids(update)[0])
    for name in values:
        record_resource_update(
            VALUE_EDIT_SECTIONS[name], name,
            source=session["input_sources"].get(name, "screenshot"),
        )
    _edit_view(update, bot, session, _finish_message(session, f"✅ Сохранено показателей: {len(values)}."))
    _answer_callback(bot, update)


class ScreenshotProgressMiddleware(NoOpPostProcessMiddleware):
    def __init__(self, bot):
        super().__init__()
        self.update_types = ["message", "callback_query"]
        self._bot = bot

    def pre_process(self, update, data):
        message = update.message if isinstance(update, CallbackQuery) else update
        if message is None or message.chat.type != "private":
            return None
        session = _load(update, self._bot, check_callback=False)
        if session is None or not session.get("pending"):
            return None
        if isinstance(update, CallbackQuery):
            if update.data == f"screenshot/{session['session_id'][:12]}/cancel":
                return None
            _answer_callback(self._bot, update, _WAIT_MESSAGE)
        else:
            command = (update.text or "").partition(" ")[0].partition("@")[0]
            if command == "/cancel":
                cancel_screenshots(update, self._bot)
                return SkipHandler()
            if update.content_type in {"photo", "document"}:
                return None
            _update_review(update, self._bot, session, _WAIT_MESSAGE)
        return SkipHandler()


def register_handlers(bot: TeleBot) -> None:
    handlers = HandlerRegistry(bot)
    handlers.private_callback(start_screenshot, button=r"screenshot/start(?:/[0-9]+)?")
    handlers.private_callback(cancel_screenshots, button=r"screenshot/[a-f0-9]{12}/cancel", state=ScreenshotStates.review)
    handlers.private_message(receive_screenshot, content_types=["photo", "document"], state=ScreenshotStates.review)
    handlers.private_message(correct_reading, content_types=["text"], state=ScreenshotStates.review)
    handlers.private_callback(save_readings, button=r"screenshot/[a-f0-9]{12}/save", state=ScreenshotStates.review)
    names = "(" + "|".join(SCREENSHOT_FIELDS) + ")"
    handlers.private_callback(edit_reading, button=rf"screenshot/[a-f0-9]{{12}}/edit/{names}", state=ScreenshotStates.review)
    handlers.private_callback(drop_reading, button=rf"screenshot/[a-f0-9]{{12}}/drop/{names}", state=ScreenshotStates.review)
