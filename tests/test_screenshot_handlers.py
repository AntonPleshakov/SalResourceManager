from pathlib import Path
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry
from telebot import TeleBot
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
from tg.metrics import ApplicationMetrics, record_resource_update, record_screenshot_processed


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
    bot = TeleBot("42:test", state_storage=StateMemoryStorage())
    bot.send_message = Mock()
    bot.send_rich_message = Mock()
    bot.edit_message_text = Mock()
    bot.answer_callback_query = Mock()
    bot.get_file = Mock(return_value=SimpleNamespace(file_size=200, file_path="file.jpg"))
    bot.download_file = Mock(return_value=b"image")
    bot.delete_message = Mock()
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
    screenshots.receive_screenshot(message(photo=True), bot)
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


def test_multiple_screenshots_merge_and_excluded_values_are_not_saved(context, monkeypatch):
    bot, users, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"shells": 96500})
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.drop_reading(review_callback(bot, "drop", "hammers"), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    current = users.get_assigned_user(42)
    assert current.hammers.value == 17
    assert current.shells.value == 96500


def test_account_switch_prevents_saving_to_either_account(context):
    bot, users, original = context
    screenshots.receive_screenshot(message(photo=True), bot)
    save = review_callback(bot, "save")
    new = users.add_account(42, "tester", "Other")
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42, original.account_id).hammers.value == 17
    assert users.get_assigned_user(42, new.account_id).hammers.value == 0
    assert bot.get_state(42) is None


def test_lost_clan_access_prevents_save(context, monkeypatch):
    bot, users, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(message(photo=True), bot)
    assert bot.get_state(42) is None
    assert users.get_assigned_user(42).hammers.value == 17


def test_oversize_photo_is_rejected_before_downloading(context):
    bot, users, _ = context
    photo = message(photo=True)
    photo.photo[-1].file_size = MAX_IMAGE_BYTES + 1
    screenshots.receive_screenshot(photo, bot)
    bot.download_file.assert_not_called()
    assert users.get_assigned_user(42).hammers.value == 17


def test_recognition_failure_keeps_previous_preview(context, monkeypatch):
    bot, users, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    save = review_callback(bot, "save")

    def failed(_):
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.save_readings(save, bot)
    assert users.get_assigned_user(42).hammers.value == 194691


def test_out_of_range_extra_egg_correction_is_rejected(context, monkeypatch):
    bot, users, _ = context
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"extra_egg_chance": 50})
    screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(first, bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"shells": 96500})
    screenshots.receive_screenshot(second, bot)
    assert bot.edit_message_text.call_count == 3
    assert all(call.kwargs["message_id"] == 1 for call in bot.edit_message_text.call_args_list)
    assert all(call.kwargs["chat_id"] == 42 for call in bot.edit_message_text.call_args_list)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "194 691" in html and "96 500" in html
    assert [call.args for call in bot.delete_message.call_args_list] == [(42, 100), (42, 101)]
    assert "Найдено показателей" not in html
    assert '<tg-button type="callback_data"' in html
    assert "<details><summary>Как работает распознавание</summary>" in html
    visible = html.split("<details>")[0]
    assert "JPEG" not in visible and "Технологии поддерживают" not in visible
    bot.send_message.assert_not_called()
    bot.send_rich_message.assert_not_called()


@pytest.mark.parametrize("empty_first", [False, True])
def test_empty_readings_do_not_replace_cumulative_information(context, monkeypatch, empty_first):
    bot, _, _ = context
    readings = [{}, {"hammers": 194691}] if empty_first else [{"hammers": 194691}, {}]
    for values in readings:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _, values=values: values)
        screenshots.receive_screenshot(message(photo=True), bot)
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
        bot.delete_message.assert_called_once_with(42, 102)
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    screenshots.receive_screenshot(document, bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Скриншот №1: Ошибка чтения" in html
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 194691})
    screenshots.receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Скриншот №1: Ошибка чтения" in html and "194 691" in html


def test_multiple_empty_screenshots_keep_separate_numbered_notices(context, monkeypatch):
    bot, _, _ = context
    for values in [{}, {"hammers": 194691}, {}, {}]:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _, values=values: values)
        screenshots.receive_screenshot(message(photo=True), bot)
    html = bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert "Получено скриншотов: 4." in html
    for number in (1, 3, 4):
        assert f"Скриншот №{number}: подходящие значения не найдены." in html
    assert "Скриншот №2:" not in html
    assert html.count("подходящие значения не найдены.") == 3
    assert "194 691" in html
    bot.send_message.assert_not_called()


def test_failed_download_is_not_deleted(context):
    bot, _, _ = context
    bot.download_file.side_effect = RuntimeError("download failed")
    screenshots.receive_screenshot(message(photo=True), bot)
    bot.delete_message.assert_not_called()


def test_text_input_is_deleted_on_both_invalid_and_valid_correction(context):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(message(photo=True), bot)
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


def test_correction_errors_and_confirmation_edit_the_original_message(context):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    assert "Введите исправленное значение" in bot.edit_message_text.call_args.kwargs["rich_message"].html
    screenshots.correct_reading(message("ошибка"), bot)
    with bot.retrieve_data(42) as data:
        assert data["screenshot_import"]["edit"] == "hammers"
    screenshots.correct_reading(message("195к"), bot)
    screenshots.save_readings(review_callback(bot, "save"), bot)
    assert "✅ Сохранено показателей: 1." in bot.edit_message_text.call_args.kwargs["rich_message"].html
    assert all(call.kwargs["message_id"] == 1 for call in bot.edit_message_text.call_args_list)
    bot.send_message.assert_not_called()
    bot.send_rich_message.assert_not_called()


def test_empty_screenshot_is_saved_before_recognition_and_logged(context, monkeypatch):
    bot, _, _ = context
    log = Mock()
    monkeypatch.setattr(screenshots, "logger", log)

    def recognize(image):
        saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
        assert saved.read_bytes() == image == b"image"
        return {}

    monkeypatch.setattr(screenshots, "recognize_screenshot", recognize)
    screenshots.receive_screenshot(message(photo=True), bot)
    saved, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
    log.warning.assert_called_once_with(
        "No screenshot values found user_id=%s screenshot_path=%s", 42, str(saved),
    )


@pytest.mark.parametrize("replacement", [{"hammers": 200000}, {"shells": 300}, {}])
def test_correction_logs_source_of_latest_reading(context, monkeypatch, replacement):
    bot, _, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    first, = screenshot_storage.SCREENSHOT_DIRECTORY.iterdir()
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: replacement)
    screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(message(photo=True), bot)
    screenshots.edit_reading(review_callback(bot, "edit", "hammers"), bot)
    screenshots.correct_reading(message("101" if corrected else "100"), bot)
    if replaced:
        monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {"hammers": 300})
        screenshots.receive_screenshot(message(photo=True), bot)
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
    screenshots.receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(screenshots, "recognize_screenshot", lambda _: {})
    screenshots.receive_screenshot(message(photo=True), bot)

    def failed(_):
        raise ScreenshotError("Ошибка чтения")

    monkeypatch.setattr(screenshots, "recognize_screenshot", failed)
    screenshots.receive_screenshot(message(photo=True), bot)
    oversized = message(photo=True)
    oversized.photo[-1].file_size = MAX_IMAGE_BYTES + 1
    screenshots.receive_screenshot(oversized, bot)
    bot.download_file.side_effect = RuntimeError("download failed")
    screenshots.receive_screenshot(message(photo=True), bot)
    for result in ("found", "empty", "failed"):
        assert input_metrics.get_sample_value("srm_screenshots_processed_total", {"result": result}) == 1


def test_failed_save_does_not_count_screenshot_values(context, input_metrics, monkeypatch):
    bot, users, _ = context
    screenshots.receive_screenshot(message(photo=True), bot)
    monkeypatch.setattr(users, "set_values", Mock(side_effect=ValueError("unavailable")))
    screenshots.save_readings(review_callback(bot, "save"), bot)
    for source in ("manual", "screenshot"):
        assert input_metrics.get_sample_value(
            "srm_resource_inputs_total", {"category": "resources", "source": source},
        ) == 0
