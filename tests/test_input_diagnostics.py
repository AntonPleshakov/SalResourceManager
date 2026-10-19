from contextlib import nullcontext
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telebot.apihelper import ApiTelegramException

from db.user_data_storage.values import UserDataValues
from resources.user_data import RESOURCE_FIELDS, UserData, parse_editable_field_value
from tg.message_updates import edit_validation_message
from tg.observability.updates import input_description
from tg.user_data.edit_value import save_value
from tg.user_data.editing_common import FillState, ValueEditState
from tg.user_data.fill import save_fill_value


def telegram_error(description="Bad Request: message is not modified", code=400):
    return ApiTelegramException(
        "editMessageText", "error", {"error_code": code, "description": description}
    )


@pytest.mark.parametrize("field", [field.name for field in RESOURCE_FIELDS])
@pytest.mark.parametrize("separator", [" ", "\u00a0", "\u202f"])
def test_resource_input_accepts_copied_thousands_separators(field, separator):
    assert parse_editable_field_value(field, f"1{separator}200") == 1200


def test_input_diagnostics_preserve_invisible_characters_without_log_line_injection():
    update = SimpleNamespace(text="1\u202f200\nWARNING forged", caption=None)
    diagnostic = input_description(update)
    assert diagnostic == "'1\\u202f200\\nWARNING forged'"
    assert "\n" not in diagnostic


@pytest.mark.parametrize("flow", ["single", "fill"])
def test_repeated_invalid_input_stays_silent_and_valid_retry_saves(monkeypatch, flow):
    user = UserData(account_id=7, user_id=42, username="tester", tag="Main")
    bot = Mock()
    if flow == "single":
        state = ValueEditState("pets", 7, 15)
        payload = {"value_edit_state": asdict(state)}
        save = save_value
    else:
        field = next(field for field in RESOURCE_FIELDS if field.name == "pets")
        state = FillState.start("reminder", (field,), user, 15)
        payload = {"fill_state": asdict(state)}
        save = save_fill_value
    bot.retrieve_data.side_effect = lambda _: nullcontext(payload)
    bot.edit_message_text.side_effect = [None, telegram_error(), None]
    database = Mock()
    database.get_assigned_user.return_value = user
    database.set_value.return_value = user
    monkeypatch.setattr("tg.user_data.get_user_data_db", lambda: database)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
        chat=SimpleNamespace(id=42), id=99, text="1,2",
    )

    save(message, bot)
    save(message, bot)

    database.set_value.assert_not_called()
    bot.delete_state.assert_not_called()
    bot.send_message.assert_not_called()

    message.text = "1\u202f200"
    save(message, bot)

    database.set_value.assert_called_once_with(
        42, "tester", "pets", 1200, account_id=7
    )
    bot.delete_state.assert_called_once_with(42)


def test_unrelated_telegram_error_is_not_treated_as_duplicate_validation():
    bot = Mock()
    bot.edit_message_text.side_effect = telegram_error("Forbidden", 403)
    with pytest.raises(ApiTelegramException):
        edit_validation_message(bot, "error", 42, 15)
    bot.send_message.assert_not_called()


def test_duplicate_validation_only_logs_a_warning(monkeypatch):
    bot = Mock()
    bot.edit_message_text.side_effect = telegram_error()
    log_warning = Mock()
    monkeypatch.setattr("tg.message_updates.logger.warning", log_warning)
    edit_validation_message(bot, "error", 42, 15)
    log_warning.assert_called_once()
    bot.send_message.assert_not_called()


def test_database_audit_reports_previous_and_saved_values_only_after_success(monkeypatch):
    user = UserData(account_id=7, user_id=42, username="tester", pets=100)
    storage = UserDataValues()
    storage.update_username = Mock()
    storage.get_assigned_user = Mock(return_value=user)
    storage._save_user = Mock()
    log_info = Mock()
    monkeypatch.setattr("db.user_data_storage.values.logger.info", log_info)

    storage.set_values(42, "tester", {"pets": 1200}, account_id=7)

    storage._save_user.assert_called_once_with(user)
    args = log_info.call_args.args
    assert args[1:6] == (42, "tester", 7, {"pets": 100}, {"pets": 1200})
    assert "result=saved" in args[0]

    log_info.reset_mock()
    storage._save_user.side_effect = RuntimeError("database locked")
    with pytest.raises(RuntimeError, match="database locked"):
        storage.set_values(42, "tester", {"pets": 1500}, account_id=7)
    log_info.assert_not_called()
