from pathlib import Path
from functools import partial
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry
from telebot import TeleBot
from telebot.handler_backends import SkipHandler
from telebot.apihelper import ApiTelegramException
from telebot.storage import StateMemoryStorage
from telebot.types import CallbackQuery, Chat, Document, Message, PhotoSize, User

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.access_group import AccessGroupDB
from db.database import Database
from db.user_data import UserDataDB
from resources.screenshot_input import MAX_IMAGE_BYTES, ScreenshotError
from resources import screenshot_storage
from tg.user_data import screenshots
from tg.metrics import ApplicationMetrics, observe_screenshot_stage, record_resource_update, record_screenshot_processed


def message(text="", *, photo=False):
    data = {"text": text}
    if photo:
        data = {"photo": [PhotoSize("file", "unique", 591, 1280, file_size=200)]}
    return Message(1, User(42, False, "Tester", username="tester"), 0,
                   Chat(42, "private"), "photo" if photo else "text", data, None)


def callback(data):
    update = message()
    return CallbackQuery("callback", update.from_user, data, "", None, update)


def review_callback(bot, action, name=""):
    with bot.retrieve_data(42) as data:
        token = data["screenshot_import"]["token"]
    return callback(f"screenshot/{token}/{action}" + (f"/{name}" if name else ""))


class DeferredWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)
        return True

    def cancel(self, session_id):
        self.jobs[:] = [job for job in self.jobs if job.session_id != session_id]

    def stop(self):
        self.jobs.clear()


def finish_screenshots(bot):
    worker = bot._screenshot_worker
    while worker.jobs:
        job = worker.jobs.pop(0)
        job.complete(job.run(), None)


def receive_screenshot(update, bot):
    screenshots.receive_screenshot(update, bot)
    finish_screenshots(bot)


def review_edits(bot):
    return [call for call in bot.edit_message_text.call_args_list
            if "rich_message" in call.kwargs and "Проверка скриншотов" in call.kwargs["rich_message"].html]


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot_storage, "SCREENSHOT_DIRECTORY", tmp_path / "screenshots")
    database = Database(tmp_path / "accounts.db")
    AccessGroupDB(database).add_group(-100123, "Clan")
    users = UserDataDB(database)
    account = users.add_account(42, "tester", "Player")
    users.set_values(42, "tester", {"hammers": 17, "shells": 19}, account_id=account.account_id)
    monkeypatch.setattr(screenshots.user_data, "get_user_data_db", lambda: users)
    monkeypatch.setattr(screenshots, "get_active_user_or_prompt", lambda *_: users.get_assigned_user(42))
    monkeypatch.setattr(screenshots, "get_current_accounts", lambda *_: users.get_accounts(42))
    monkeypatch.setattr(screenshots, "ocr_available", lambda: True)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 194691})
    bot = TeleBot("42:test", state_storage=StateMemoryStorage(), num_threads=1)
    bot.send_message = Mock(return_value=SimpleNamespace(message_id=900))
    bot._screenshot_worker = DeferredWorker()
    bot.send_rich_message = Mock(return_value=SimpleNamespace(message_id=900))
    bot.edit_message_text = Mock()
    bot.answer_callback_query = Mock()
    bot.get_file = Mock(return_value=SimpleNamespace(file_size=200, file_path="file.jpg"))
    bot.download_file = Mock(return_value=b"image")
    bot.delete_message = Mock()
    bot.delete_messages = Mock()
    screenshots.start_screenshot(callback("screenshot/start"), bot)
    return bot, users, account


@pytest.fixture
def input_metrics(context, monkeypatch):
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    monkeypatch.setattr(screenshots, "record_resource_update", partial(record_resource_update, metrics=metrics))
    monkeypatch.setattr(screenshots, "record_screenshot_processed", partial(record_screenshot_processed, metrics=metrics))
    return registry


def test_preview_correction_and_confirmation_save_only_found_values(context):
    bot, users, account = context
    receive_screenshot(message(photo=True), bot)
    assert users.get_assigned_user(42).hammers.value == 17
    old_save = review_callback(bot, "save")
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.save_readings(old_save, bot)
    assert users.get_assigned_user(42).hammers.value == 17
    screenshots.correct_reading(message("195к"), bot)
    screenshots.save_readings(old_save, bot)
    assert users.get_assigned_user(42).hammers.value == 17
    save = review_callback(bot, "save")
    screenshots.save_readings(save, bot)
    current = users.get_assigned_user(42)
    assert current.hammers.value == 195000
    assert current.shells.value == 19
    assert current.get_updated_on("hammers") is not None
    assert bot.get_state(42) is None
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42).hammers.value == 195000


def test_unchanged_screenshot_is_deleted_only_after_database_save(context, monkeypatch):
    bot, users, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 123, "shells": 456})
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        path = Path(data["screenshot_import"]["sources"]["hammers"])
    original_save = users.set_values

    def save(*args, **kwargs):
        assert path.is_file()
        return original_save(*args, **kwargs)

    monkeypatch.setattr(users, "set_values", save)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert not path.exists()
    assert users.get_assigned_user(42).hammers.value == 123
    assert users.get_assigned_user(42).shells.value == 456


def test_database_failure_preserves_screenshot_and_review(context, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        path = Path(data["screenshot_import"]["sources"]["hammers"])
    monkeypatch.setattr(users, "set_values", Mock(side_effect=ValueError("save failed")))
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert path.is_file()
    assert bot.get_state(42) == screenshots.ScreenshotStates.review.name
    assert users.get_assigned_user(42).hammers.value == 17


@pytest.mark.parametrize("failed", [False, True])
def test_problem_screenshot_keeps_original_warning_without_duplicates(context, monkeypatch, failed):
    bot, _, _ = context
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)

    def recognize(_):
        if failed:
            raise ScreenshotError("Ошибка чтения")
        return {}

    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        problem_path = next(iter(data["screenshot_import"]["screenshot_readings"]))
    log.warning.assert_called_once()
    assert problem_path in log.warning.call_args.args
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 123})
    receive_screenshot(message(photo=True), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert Path(problem_path).is_file()
    log.warning.assert_called_once()


def test_delete_failure_keeps_file_logs_warning_and_finishes_save(context, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        path = data["screenshot_import"]["sources"]["hammers"]
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)
    monkeypatch.setattr(screenshots, "delete_screenshot", Mock(side_effect=PermissionError))
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert Path(path).is_file()
    assert users.get_assigned_user(42).hammers.value == 194691
    assert bot.get_state(42) is None
    log.warning.assert_called_once_with(
        "Screenshot retained user_id=%s screenshot_path=%s reason=%s", 42, path, "delete_failed",
    )


@pytest.mark.parametrize("action", ["excluded", "replaced", "edited", "reverted"])
def test_unconfirmed_original_is_retained_with_warning_once(context, monkeypatch, action):
    bot, _, _ = context
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 100, "shells": 200})
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        original = Path(data["screenshot_import"]["sources"]["hammers"])
    if action == "excluded":
        screenshots.drop_reading(review_callback(bot, "drop", "hammers"), bot)
    elif action == "replaced":
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 100})
        receive_screenshot(message(photo=True), bot)
    else:
        screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
        screenshots.correct_reading(message("101"), bot)
        if action == "reverted":
            screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
            screenshots.correct_reading(message("100"), bot)
    warnings_before_save = log.warning.call_count
    assert warnings_before_save == (2 if action == "reverted" else 1)
    assert str(original) in log.warning.call_args.args
    if action in {"excluded", "replaced"}:
        assert log.warning.call_args.args[-1] == action
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert original.is_file()
    assert list(screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()) == [original]
    assert log.warning.call_count == warnings_before_save


@pytest.mark.parametrize("values", [{"hammers": 100}, {}])
def test_cancel_deletes_completed_files_including_empty_results(context, monkeypatch, values):
    from tg import navigation

    bot, _, _ = context
    monkeypatch.setattr(navigation, "home", lambda update, bot, **kwargs: bot.delete_state(42))
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: values)
    receive_screenshot(message(photo=True), bot)
    with bot.retrieve_data(42) as data:
        session = data["screenshot_import"]
        paths = list(session["screenshot_readings"])
        cancel = callback(f"screenshot/{session['session_id'][:12]}/cancel")
    assert all(Path(path).is_file() for path in paths)
    screenshots.cancel_screenshots(cancel, bot)
    assert all(not Path(path).exists() for path in paths)


def test_cancel_during_real_ocr_deletes_late_file(context, monkeypatch):
    from tg import navigation

    bot, users, _ = context
    del bot._screenshot_worker
    started, release, deleted = Event(), Event(), Event()
    delete = screenshots.delete_screenshot

    def recognize(_):
        started.set()
        assert release.wait(5)
        return {"hammers": 100}

    def remove(path):
        delete(path)
        deleted.set()

    monkeypatch.setattr(navigation, "home", lambda update, bot, **kwargs: bot.delete_state(42))
    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    monkeypatch.setattr(screenshots, "delete_screenshot", remove)
    try:
        screenshots.receive_screenshot(message(photo=True), bot)
        assert started.wait(5)
        saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
        with bot.retrieve_data(42) as data:
            cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
        screenshots.cancel_screenshots(cancel, bot)
        release.set()
        assert deleted.wait(5)
        assert not saved.exists()
        assert users.get_assigned_user(42).hammers.value == 17
        assert bot.get_state(42) is None
    finally:
        release.set()
        screenshots.stop_screenshot_worker(bot)
        bot.stop_bot()


@pytest.mark.parametrize("failure", [None, "download", "recognize"])
def test_stage_metrics_measure_failed_and_successful_attempts_separately(context, monkeypatch, failure):
    bot, _, _ = context
    registry = CollectorRegistry()
    metrics = ApplicationMetrics(registry)
    now = [0.0]

    def download(_):
        now[0] += 1
        if failure == "download":
            raise RuntimeError("download failed")
        return b"image"

    def recognize(_):
        now[0] += 3
        if failure == "recognize":
            raise ScreenshotError("OCR failed")
        return {"hammers": 100}

    monkeypatch.setattr(screenshots, "observe_screenshot_stage", partial(
        observe_screenshot_stage, metrics=metrics, clock=lambda: now[0],
    ))
    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    bot.download_file.side_effect = download
    receive_screenshot(message(photo=True), bot)
    assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_sum", {"stage": "download"}) == 1
    assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_count", {"stage": "download"}) == 1
    assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_sum", {"stage": "recognize"}) == (0 if failure == "download" else 3)
    assert registry.get_sample_value("srm_screenshot_stage_duration_seconds_count", {"stage": "recognize"}) == (0 if failure == "download" else 1)


def test_multiple_screenshots_merge_and_excluded_values_are_not_saved(context, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"shells": 96500})
    receive_screenshot(message(photo=True), bot)
    screenshots.drop_reading(review_callback(bot, "drop", "hammers"), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    current = users.get_assigned_user(42)
    assert current.hammers.value == 17
    assert current.shells.value == 96500


def test_account_switch_prevents_saving_to_either_account(context):
    bot, users, original = context
    receive_screenshot(message(photo=True), bot)
    save = review_callback(bot, "save")
    new = users.add_account(42, "tester", "Other")
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42, original.account_id).hammers.value == 17
    assert users.get_assigned_user(42, new.account_id).hammers.value == 0
    assert bot.get_state(42) is None


def test_lost_clan_access_prevents_save(context, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    save = review_callback(bot, "save")
    monkeypatch.setattr(screenshots, "get_active_user_or_prompt", lambda *_: None)
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42).hammers.value == 17


def test_cancel_during_recognition_does_not_recreate_session(context, monkeypatch):
    bot, users, _ = context

    def cancelled(_):
        bot.delete_state(42)
        return {"hammers": 194691}

    monkeypatch.setattr(screenshots, "recognize_screenshot", cancelled)
    receive_screenshot(message(photo=True), bot)
    assert bot.get_state(42) is None
    assert users.get_assigned_user(42).hammers.value == 17


def test_oversize_photo_is_rejected_before_downloading(context):
    bot, users, _ = context
    photo = message(photo=True)
    photo.photo[-1].file_size = MAX_IMAGE_BYTES + 1
    receive_screenshot(photo, bot)
    bot.download_file.assert_not_called()
    assert users.get_assigned_user(42).hammers.value == 17


def test_recognition_failure_keeps_previous_preview(context, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    save = review_callback(bot, "save")

    def failed(_):
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    receive_screenshot(message(photo=True), bot)
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42).hammers.value == 194691


def test_out_of_range_extra_egg_correction_is_rejected(context, monkeypatch):
    bot, users, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"extra_egg_chance": 50})
    receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "extra_egg_chance"), bot)
    screenshots.correct_reading(message("51"), bot)
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["values"] == {"extra_egg_chance": 50}
        assert data["screenshot_import"]["edit"] == "extra_egg_chance"


def test_missing_tesseract_is_reported_in_chat(context, monkeypatch):
    bot, _, _ = context
    bot.delete_state(42)
    bot.edit_message_text.reset_mock()
    monkeypatch.setattr(screenshots, "ocr_available", lambda: False)
    screenshots.start_screenshot(callback("screenshot/start"), bot)
    assert bot.get_state(42) is None
    assert "Tesseract" in bot.edit_message_text.call_args.kwargs["rich_message"].html
    bot.send_message.assert_not_called()


def test_album_updates_one_rich_message_with_all_accumulated_values(context, monkeypatch):
    bot, _, _ = context
    first = message(photo=True)
    first.id = 100
    first.media_group_id = "album"
    second = message(photo=True)
    second.id = 101
    second.media_group_id = "album"
    receive_screenshot(first, bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"shells": 96500})
    receive_screenshot(second, bot)
    assert len(review_edits(bot)) == 3
    assert all(call.kwargs["message_id"] in {1, 900} for call in review_edits(bot))
    assert all(call.kwargs["chat_id"] == 42 for call in review_edits(bot))
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "194 691" in html and "96 500" in html
    assert [call.args for call in bot.delete_message.call_args_list] == [(42, 1), (42, 100), (42, 900), (42, 101)]
    assert "Найдено показателей" not in html
    assert '<tg-button type="callback_data"' in html
    assert "<details><summary>Как работает распознавание</summary>" in html
    visible = html.split("<details>")[0]
    assert "JPEG" not in visible and "Технологии поддерживают" not in visible
    assert all("Распознавание скриншотов" in call.args[1] for call in bot.send_message.call_args_list)
    assert all("Распознавание скриншотов" in call.args[1].html for call in bot.send_rich_message.call_args_list)


@pytest.mark.parametrize("empty_first", [False, True])
def test_empty_readings_do_not_replace_cumulative_information(context, monkeypatch, empty_first):
    bot, _, _ = context
    readings = [{}, {"hammers": 194691}] if empty_first else [{"hammers": 194691}, {}]
    for values in readings:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _, values=values: values)
        receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "194 691" in html
    empty_number = 1 if empty_first else 2
    warning = f"Скриншот №{empty_number}: подходящие значения не найдены."
    assert warning in html
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("195к"), bot)
    assert warning in bot.edit_message_text.call_args.kwargs["rich_message"].html
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert warning in bot.edit_message_text.call_args.kwargs["rich_message"].html


def test_downloaded_document_is_deleted_even_if_recognition_fails(context, monkeypatch):
    bot, _, _ = context
    document = message()
    document.id = 102
    document.content_type = "document"
    document.document = Document("file", "unique", file_size=200)

    def failed(_):
        bot.delete_message.assert_any_call(42, 102)
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    receive_screenshot(document, bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Скриншот №1: Ошибка чтения" in html
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 194691})
    receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Скриншот №1: Ошибка чтения" in html and "194 691" in html


def test_multiple_empty_screenshots_keep_separate_numbered_notices(context, monkeypatch):
    bot, _, _ = context
    for values in [{}, {"hammers": 194691}, {}, {}]:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _, values=values: values)
        receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Получено скриншотов: 4." in html
    for number in (1, 3, 4):
        assert f"Скриншот №{number}: подходящие значения не найдены." in html
    assert "Скриншот №2:" not in html
    assert html.count("подходящие значения не найдены.") == 3
    assert "194 691" in html
    assert bot.send_rich_message.call_count == 4


def test_failed_download_is_not_deleted(context):
    bot, _, _ = context
    bot.download_file.side_effect = RuntimeError("download failed")
    photo = message(photo=True)
    photo.id = 100
    receive_screenshot(photo, bot)
    bot.delete_message.assert_called_once_with(42, 1)


def test_text_input_is_deleted_on_both_invalid_and_valid_correction(context):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    bot.delete_message.reset_mock()
    invalid, valid = message("ошибка"), message("195к")
    invalid.id, valid.id = 103, 104
    screenshots.correct_reading(invalid, bot)
    screenshots.correct_reading(valid, bot)
    assert [call.args for call in bot.delete_message.call_args_list] == [(42, 103), (42, 104)]


def test_telegram_deletion_failure_does_not_discard_readings(context):
    bot, _, _ = context
    bot.delete_message.side_effect = ApiTelegramException("deleteMessage", None, {
        "ok": False, "error_code": 400, "description": "message can't be deleted",
    })
    receive_screenshot(message(photo=True), bot)
    assert "194 691" in bot.edit_message_text.call_args.kwargs["rich_message"].html


def test_reminder_screenshot_button_selects_its_account(context):
    bot, users, original = context
    users.add_account(42, "tester", "Other")
    screenshots.start_screenshot(callback(f"screenshot/start/{original.account_id}"), bot)
    assert users.get_assigned_user(42).account_id.value == original.account_id
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["account_id"] == original.account_id


def test_reminder_cannot_select_another_users_account(context):
    bot, users, original = context
    foreign = users.add_account(99, "other", "Foreign")
    screenshots.start_screenshot(callback(f"screenshot/start/{foreign.account_id}"), bot)
    assert users.get_assigned_user(42).account_id.value == original.account_id
    assert "Аккаунт недоступен" in bot.edit_message_text.call_args.kwargs["rich_message"].html


def test_correction_errors_and_confirmation_edit_the_result_message(context):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    assert "Введите исправленное значение" in bot.edit_message_text.call_args.kwargs["rich_message"].html
    screenshots.correct_reading(message("ошибка"), bot)
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["edit"] == "hammers"
    screenshots.correct_reading(message("195к"), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert "✅ Сохранено показателей: 1." in bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert all(call.kwargs["message_id"] in {1, 900} for call in review_edits(bot))
    assert all("Распознавание скриншотов" in call.args[1] for call in bot.send_message.call_args_list)
    assert all("Распознавание скриншотов" in call.args[1].html for call in bot.send_rich_message.call_args_list)


def test_empty_screenshot_is_saved_before_recognition_and_logged(context, monkeypatch):
    bot, _, _ = context
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)

    def recognize(image):
        saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
        assert saved.read_bytes() == image == b"image"
        return {}

    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    receive_screenshot(message(photo=True), bot)
    saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
    log.warning.assert_called_once_with(
        "No screenshot values found user_id=%s screenshot_path=%s", 42, str(saved),
    )


@pytest.mark.parametrize("replacement", [{"hammers": 200000}, {"shells": 300}, {}])
def test_correction_logs_source_of_latest_reading(context, monkeypatch, replacement):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    first, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: replacement)
    receive_screenshot(message(photo=True), bot)
    latest = max(screenshot_storage.SCREENSHOT_DIRECTORY.iterdir())
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("ошибка"), bot)
    old_value = replacement.get("hammers", 194691)
    screenshots.correct_reading(message(str(old_value)), bot)
    log.warning.assert_not_called()
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("195к"), bot)
    log.warning.assert_called_once_with(
        "Screenshot value corrected user_id=%s field=%s old_value=%s new_value=%s screenshot_path=%s",
        42, "hammers", old_value, 195000,
        str(latest if "hammers" in replacement else first),
    )


def test_unreadable_screenshot_is_retained_and_logged(context, monkeypatch):
    bot, _, _ = context
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)

    def failed(_):
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    receive_screenshot(message(photo=True), bot)
    saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
    assert saved.read_bytes() == b"image"
    log.warning.assert_called_once_with(
        "Screenshot recognition failed user_id=%s screenshot_path=%s", 42, str(saved),
    )


@pytest.mark.parametrize("corrected,replaced", [(False, False), (True, False), (True, True)])
def test_saved_screenshot_metrics_use_final_source_and_exclude_dropped_fields(
    context, input_metrics, monkeypatch, corrected, replaced,
):
    bot, _, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 100, "shells": 200})
    receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("101" if corrected else "100"), bot)
    if replaced:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 300})
        receive_screenshot(message(photo=True), bot)
    screenshots.drop_reading(review_callback(bot, "drop", "shells"), bot)
    labels = {"category": "resources", "source": "manual"}
    assert input_metrics.get_sample_value("srm_resource_inputs_total", labels) == 0
    assert input_metrics.get_sample_value("srm_resource_inputs_total", {**labels, "source": "screenshot"}) == 0
    save = review_callback(bot, "save")
    screenshots.save_readings(save, bot)
    screenshots.save_readings(save, bot)
    manual = int(corrected and not replaced)
    assert input_metrics.get_sample_value("srm_resource_inputs_total", labels) == manual
    assert input_metrics.get_sample_value("srm_resource_inputs_total", {**labels, "source": "screenshot"}) == 1 - manual


def test_screenshot_metrics_count_recognition_outcomes(context, input_metrics, monkeypatch):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {})
    receive_screenshot(message(photo=True), bot)

    def failed(_):
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    receive_screenshot(message(photo=True), bot)
    oversized = message(photo=True)
    oversized.photo[-1].file_size = MAX_IMAGE_BYTES + 1
    receive_screenshot(oversized, bot)
    bot.download_file.side_effect = RuntimeError("download failed")
    receive_screenshot(message(photo=True), bot)
    for result in ("found", "empty", "failed"):
        assert input_metrics.get_sample_value("srm_screenshots_processed_total", {"result": result}) == 1


def test_failed_save_does_not_count_screenshot_values(context, input_metrics, monkeypatch):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(users, "set_values", Mock(side_effect=ValueError("unavailable")))
    screenshots.save_readings(review_callback(bot, "save"), bot)
    for source in ("manual", "screenshot"):
        assert input_metrics.get_sample_value(
            "srm_resource_inputs_total", {"category": "resources", "source": source},
        ) == 0


def test_pending_album_has_one_progress_message_and_merges_all_results(context, monkeypatch):
    bot, users, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", Mock(side_effect=[
        {"hammers": 100}, {"shells": 200},
    ]))
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    assert bot.send_rich_message.call_count == 1
    assert "Обработано 0 из 1." in bot.send_rich_message.call_args.args[1].html
    assert any("Обработано 0 из 2." in call.kwargs["rich_message"].html
               for call in bot.edit_message_text.call_args_list)
    bot.download_file.assert_not_called()
    first = bot._screenshot_worker.jobs.pop(0)
    first.complete(first.run(), None)
    assert "Обработано 1 из 2." in bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert len(review_edits(bot)) == 1
    assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    finish_screenshots(bot)
    assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    with bot.retrieve_data(42) as data:
        session = data["screenshot_import"]
        assert session["values"] == {"hammers": 100, "shells": 200}
        assert session["pending"] == 0
    assert users.get_assigned_user(42).hammers.value == 17
    assert not screenshots._uploads(bot)


@pytest.mark.parametrize("action", ["save", "edit", "drop"])
def test_pending_screenshots_block_save_edit_and_drop(context, action):
    bot, users, _ = context
    receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    handlers = {"save": screenshots.save_readings, "edit": screenshots.edit_reading,
                "drop": screenshots.drop_reading}
    handlers[action](review_callback(bot, action, "hammers" if action != "save" else ""), bot)
    assert bot.answer_callback_query.call_args.args[1] == "Дождитесь окончания распознавания."
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["values"] == {"hammers": 194691}
        assert data["screenshot_import"].get("edit") is None
    assert users.get_assigned_user(42).hammers.value == 17


@pytest.mark.parametrize("target", ["home", "settings", "accounts/resources", "screenshot/start"])
def test_middleware_blocks_navigation_while_recognizing(context, target):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    result = screenshots.ScreenshotProgressMiddleware(bot).pre_process(callback(target), {})
    assert isinstance(result, SkipHandler)
    assert bot.get_state(42) == screenshots.ScreenshotStates.review.name
    assert bot.answer_callback_query.call_args.args[1] == "Дождитесь окончания распознавания."


@pytest.mark.parametrize("command", ["/menu", "/start", "/menu@bot"])
def test_middleware_blocks_menu_commands_while_recognizing(context, command):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    result = screenshots.ScreenshotProgressMiddleware(bot).pre_process(message(command), {})
    assert isinstance(result, SkipHandler)
    assert "Дождитесь окончания распознавания" in bot.edit_message_text.call_args.kwargs["rich_message"].html


def test_middleware_accepts_more_images_and_explicit_cancel(context):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    middleware = screenshots.ScreenshotProgressMiddleware(bot)
    assert middleware.pre_process(message(photo=True), {}) is None
    with bot.retrieve_data(42) as data:
        cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
    assert middleware.pre_process(cancel, {}) is None
    html = bot.send_rich_message.call_args.args[1].html
    assert cancel.data in html
    assert 'data="home"' not in html


@pytest.mark.parametrize("command", [False, True])
def test_explicit_cancel_reuses_progress_and_discards_active_and_queued_results(context, monkeypatch, command):
    from tg import navigation

    bot, users, _ = context
    home = Mock(side_effect=lambda update, bot, **kwargs: bot.delete_state(42))
    monkeypatch.setattr(navigation, "home", home)
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    active = bot._screenshot_worker.jobs.pop(0)
    result = active.run()
    with bot.retrieve_data(42) as data:
        cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
    if command:
        response = screenshots.ScreenshotProgressMiddleware(bot).pre_process(message("/cancel"), {})
        assert isinstance(response, SkipHandler)
    else:
        screenshots.cancel_screenshots(cancel, bot)
    home.assert_called_once()
    assert not bot._screenshot_worker.jobs
    assert not screenshots._uploads(bot)
    assert home.call_args.kwargs == {"edit_message_id": 900}
    assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    active.complete(result, None)
    assert bot.get_state(42) is None
    assert users.get_assigned_user(42).hammers.value == 17


def test_queue_overflow_keeps_input_and_does_not_increment_progress(context):
    bot, _, _ = context
    bot._screenshot_worker.submit = Mock(return_value=False)
    screenshots.receive_screenshot(message(photo=True), bot)
    bot.download_file.assert_not_called()
    bot.delete_message.assert_not_called()
    bot.send_message.assert_not_called()
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["pending"] == 0
        assert data["screenshot_import"].get("screenshot_count", 0) == 0
    assert "Очередь распознавания заполнена" in bot.edit_message_text.call_args.kwargs["rich_message"].html


def test_failed_screenshot_replaces_progress_with_result_and_reports_its_original_number(context, monkeypatch):
    bot, _, _ = context
    recognize = Mock(side_effect=[ScreenshotError("Ошибка чтения"), {"hammers": 100}])
    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    finish_screenshots(bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Скриншот №1: Ошибка чтения" in html
    assert "Скриншот №2: Ошибка чтения" not in html
    assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    assert not screenshots._uploads(bot)


def test_late_result_does_not_modify_a_new_session(context):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    active = bot._screenshot_worker.jobs.pop(0)
    result = active.run()
    screenshots.start_screenshot(callback("screenshot/start"), bot)
    active.complete(result, None)
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["values"] == {}
    assert not screenshots._uploads(bot)


def test_expired_preview_callback_does_not_raise(context):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    stale = review_callback(bot, "save")
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("195к"), bot)
    bot.answer_callback_query.side_effect = ApiTelegramException("answerCallbackQuery", None, {
        "ok": False, "error_code": 400,
        "description": "Bad Request: query is too old and response timeout expired or query ID is invalid",
    })
    screenshots.save_readings(stale, bot)


def test_stop_clears_pending_work_and_progress(context):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.stop_screenshot_worker(bot)
    assert not bot._screenshot_worker.jobs
    assert not screenshots._uploads(bot)
    assert [call.args for call in bot.delete_message.call_args_list] == [(42, 1), (42, 900)]


def test_real_ocr_worker_leaves_single_telegram_worker_free_and_applies_result_there(context, monkeypatch):
    bot, _, _ = context
    del bot._screenshot_worker
    started, release, unrelated, finished = Event(), Event(), Event(), Event()
    threads = {}
    complete = screenshots._complete_screenshot

    def recognize(_):
        threads["ocr"] = get_ident()
        started.set()
        assert release.wait(5)
        return {"hammers": 194691}

    def handle_unrelated_event():
        threads["telegram"] = get_ident()
        unrelated.set()

    def apply_result(*args):
        threads["result"] = get_ident()
        complete(*args)
        finished.set()

    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    monkeypatch.setattr(screenshots, "_complete_screenshot", apply_result)
    try:
        bot.worker_pool.put(screenshots.receive_screenshot, message(photo=True), bot)
        assert started.wait(5)
        bot.worker_pool.put(handle_unrelated_event)
        assert unrelated.wait(5)
        assert not finished.is_set()
        release.set()
        assert finished.wait(5)
        assert threads["ocr"] != threads["telegram"] == threads["result"]
        with bot.retrieve_data(42) as data:
            assert data["screenshot_import"]["pending"] == 0
            assert data["screenshot_import"]["values"] == {"hammers": 194691}
        assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    finally:
        release.set()
        screenshots.stop_screenshot_worker(bot)
        bot.stop_bot()


@pytest.mark.parametrize("failure", ["send", "edit", "delete"])
def test_progress_network_failure_does_not_discard_results_or_leave_session_pending(context, failure):
    bot, _, _ = context

    def edit(**kwargs):
        if "Распознавание скриншотов" in kwargs["rich_message"].html:
            raise RuntimeError("private-network-error")

    def delete(chat_id, message_id):
        if message_id == 1:
            raise RuntimeError("private-network-error")

    if failure == "send":
        bot.send_rich_message.side_effect = [RuntimeError("private-network-error"), SimpleNamespace(message_id=900)]
    elif failure == "edit":
        bot.edit_message_text.side_effect = edit
    else:
        bot.delete_message.side_effect = delete
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    finish_screenshots(bot)
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["pending"] == 0
        assert data["screenshot_import"]["values"] == {"hammers": 194691}
    assert not screenshots._uploads(bot)


def test_prompt_is_deleted_before_progress_and_result_replaces_progress_after_all_inputs(context, monkeypatch):
    bot, _, _ = context
    calls = Mock()
    calls.attach_mock(bot.delete_message, "delete")
    calls.attach_mock(bot.send_rich_message, "send")
    calls.attach_mock(bot.edit_message_text, "edit")
    monkeypatch.setattr(screenshots, "recognize_screenshot", Mock(side_effect=[
        {"hammers": 194691}, {"shells": 96500},
    ]))
    first, second = message(photo=True), message(photo=True)
    first.id, second.id = 100, 101
    screenshots.receive_screenshot(first, bot)
    screenshots.receive_screenshot(second, bot)
    assert calls.mock_calls[0].args == (42, 1)
    assert calls.mock_calls[0][0] == "delete"
    assert calls.mock_calls[1][0] == "send"
    progress = calls.mock_calls[1].args[1].html
    assert "Обработано 0 из 1" in progress and "✖️ Отмена" in progress
    active = bot._screenshot_worker.jobs.pop(0)
    active.complete(active.run(), None)
    assert all("194 691" not in call.kwargs["rich_message"].html
               for call in bot.edit_message_text.call_args_list[1:])
    finish_screenshots(bot)
    final = calls.mock_calls[-1]
    assert final[0] == "edit" and final.kwargs["message_id"] == 900
    html = final.kwargs["rich_message"].html
    for text in ("194 691", "96 500", "✏️ Изменить", "✖️ Исключить", "✅ Сохранить найденное"):
        assert text in html
    assert [(call.args) for call in calls.mock_calls if call[0] == "delete"] == [
        (42, 1), (42, 100), (42, 101),
    ]


def test_additional_upload_hides_previous_result_and_uses_new_progress_message(context, monkeypatch):
    bot, _, _ = context
    bot.send_rich_message.side_effect = [SimpleNamespace(message_id=900), SimpleNamespace(message_id=901)]
    receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"shells": 96500})
    bot.edit_message_text.reset_mock()
    screenshots.receive_screenshot(message(photo=True), bot)
    bot.delete_message.assert_any_call(42, 900)
    assert "194 691" not in bot.send_rich_message.call_args.args[1].html
    bot.edit_message_text.assert_not_called()
    finish_screenshots(bot)
    final = bot.edit_message_text.call_args.kwargs
    assert final["message_id"] == 901
    assert "194 691" in final["rich_message"].html and "96 500" in final["rich_message"].html
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["prompt_message_id"] == 901


@pytest.mark.parametrize("command", [False, True])
def test_cancel_replaces_progress_with_main_menu_without_sending_another_message(context, monkeypatch, command):
    from tg import navigation

    bot, users, _ = context
    monkeypatch.setattr(navigation, "_show_onboarding", lambda *_: False)
    monkeypatch.setattr(navigation, "get_user_data_db", lambda: users)
    monkeypatch.setattr(navigation, "get_admins_db", lambda: SimpleNamespace(has_admin_access=lambda _: False))
    screenshots.receive_screenshot(message(photo=True), bot)
    active = bot._screenshot_worker.jobs.pop(0)
    result = active.run()
    with bot.retrieve_data(42) as data:
        cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
    if command:
        screenshots.ScreenshotProgressMiddleware(bot).pre_process(message("/cancel"), {})
    else:
        screenshots.cancel_screenshots(cancel, bot)
    final = bot.edit_message_text.call_args.kwargs
    assert final["message_id"] == 900
    assert "Главное меню" in final["rich_message"].html
    assert bot.send_rich_message.call_count == 1
    assert (42, 900) not in [call.args for call in bot.delete_message.call_args_list]
    assert bot.get_state(42) is None
    active.complete(result, None)
    assert bot.edit_message_text.call_args.kwargs == final


def test_overflow_and_menu_attempts_keep_only_progress_visible(context):
    bot, _, _ = context
    receive_screenshot(message(photo=True), bot)
    screenshots.receive_screenshot(message(photo=True), bot)
    bot._screenshot_worker.submit = Mock(return_value=False)
    bot.edit_message_text.reset_mock()
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.ScreenshotProgressMiddleware(bot).pre_process(message("/menu"), {})
    for call in bot.edit_message_text.call_args_list:
        html = call.kwargs["rich_message"].html
        assert "Распознавание скриншотов" in html and "194 691" not in html
        assert "✖️ Отмена" in html


@pytest.mark.parametrize("command", [False, True])
def test_cancel_deletes_active_and_queued_screenshots_without_recognizing_the_queue(context, monkeypatch, command):
    from tg import navigation

    bot, _, _ = context
    monkeypatch.setattr(navigation, "home", Mock(side_effect=lambda update, bot, **kwargs: bot.delete_state(42)))
    first, second, third = [message(photo=True) for _ in range(3)]
    first.id, second.id, third.id = 100, 101, 102
    for photo in (first, second, third):
        screenshots.receive_screenshot(photo, bot)
    active = bot._screenshot_worker.jobs.pop(0)
    result = active.run()
    with bot.retrieve_data(42) as data:
        cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
    if command:
        screenshots.ScreenshotProgressMiddleware(bot).pre_process(message("/cancel"), {})
    else:
        screenshots.cancel_screenshots(cancel, bot)
    bot.delete_messages.assert_called_once_with(42, [100, 101, 102])
    assert bot.download_file.call_count == 1
    assert not bot._screenshot_worker.jobs
    active.complete(result, None)
    assert bot.get_state(42) is None


def test_cancel_also_deletes_images_rejected_by_size_or_queue_limit(context, monkeypatch):
    from tg import navigation

    bot, _, _ = context
    monkeypatch.setattr(navigation, "home", Mock(side_effect=lambda update, bot, **kwargs: bot.delete_state(42)))
    first, oversized, overflow = [message(photo=True) for _ in range(3)]
    first.id, oversized.id, overflow.id = 100, 101, 102
    screenshots.receive_screenshot(first, bot)
    oversized.photo[-1].file_size = MAX_IMAGE_BYTES + 1
    screenshots.receive_screenshot(oversized, bot)
    bot._screenshot_worker.submit = Mock(return_value=False)
    screenshots.receive_screenshot(overflow, bot)
    with bot.retrieve_data(42) as data:
        cancel = callback(f"screenshot/{data['screenshot_import']['session_id'][:12]}/cancel")
    screenshots.cancel_screenshots(cancel, bot)
    bot.delete_messages.assert_called_once_with(42, [100, 101, 102])
    bot.download_file.assert_not_called()


def test_cancel_deletes_only_current_session_screenshots_and_uses_batches_of_100(context, monkeypatch):
    from tg import navigation

    bot, _, _ = context
    home = Mock(side_effect=lambda update, bot, **kwargs: bot.delete_state(42))
    monkeypatch.setattr(navigation, "home", home)
    with bot.retrieve_data(42) as data:
        session = data["screenshot_import"]
        session["screenshot_message_ids"] = list(range(100, 305))
        cancel = callback(f"screenshot/{session['session_id'][:12]}/cancel")
    bot.delete_messages.side_effect = [RuntimeError("private-network-error"), True, True]
    screenshots.cancel_screenshots(cancel, bot)
    assert [call.args for call in bot.delete_messages.call_args_list] == [
        (42, list(range(100, 200))), (42, list(range(200, 300))), (42, list(range(300, 305))),
    ]
    home.assert_called_once()


@pytest.mark.parametrize("field,title,count", [("pets", "Питомцы и яйца", 96), ("unmerged_mounts", "Необъединённые маунты", 357)])
@pytest.mark.parametrize("corrected", [False, True])
def test_selection_count_is_reviewed_and_saved(context, input_metrics, monkeypatch, field, title, count, corrected):
    bot, users, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {field: count})
    receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert title in html and str(count) in html
    assert f"/edit/{field}" in html and f"/drop/{field}" in html
    assert getattr(users.get_assigned_user(42), field).value == 0
    if corrected:
        screenshots.edit_reading(review_callback(bot, "edit", field), bot)
        screenshots.correct_reading(message(str(count + 1)), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert getattr(users.get_assigned_user(42), field).value == count + int(corrected)
    assert input_metrics.get_sample_value("srm_resource_inputs_total", {
        "category": "resources", "source": "manual" if corrected else "screenshot",
    }) == 1
