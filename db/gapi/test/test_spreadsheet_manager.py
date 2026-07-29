import time

import pytest

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.spreadsheet_manager import SpreadsheetManager, DEFAULT_WORKSHEET_NAME


@pytest.fixture
def manager_factory():
    def create_manager(spreadsheet_name: str) -> SpreadsheetManager:
        return GSheetsManager().open(spreadsheet_name)

    return create_manager


@pytest.fixture
def manager(manager_factory):
    ss_name = getconf("TEST_GTABLE_KEY")
    return manager_factory(ss_name)


@pytest.mark.gdrive_access
@pytest.mark.parametrize(
    "worksheet_name, is_exist",
    [(getconf("TEST_PAGE_NAME"), True), ("test", False)],
)
def test_worksheet_existence(
    manager: SpreadsheetManager, worksheet_name: str, is_exist: bool
):
    assert manager.is_worksheet_exist(worksheet_name) == is_exist


@pytest.mark.gdrive_access
@pytest.mark.slow
def test_ws_creation(manager: SpreadsheetManager):
    ws_name = "test"
    assert not manager.is_worksheet_exist(ws_name)

    # Create a worksheet
    manager.add_worksheet(ws_name)
    cnt = 0
    while (not manager.is_worksheet_exist(ws_name)) and (cnt < 20):
        time.sleep(0.1)
        cnt += 1
    assert cnt < 20

    # Delete the worksheet
    manager.delete_worksheet(ws_name)
    assert not manager.is_worksheet_exist(ws_name)


@pytest.mark.gdrive_access
def test_ws_open(manager: SpreadsheetManager):
    ws_name = getconf("TEST_PAGE_NAME")
    ws = manager.get_worksheet(ws_name)
    assert ws._ws.title == ws_name


@pytest.mark.parametrize(
    "new_name, old_name",
    [
        ("Test", getconf("TEST_PAGE_NAME")),
        (DEFAULT_WORKSHEET_NAME, "Test"),
        ("Test2", ""),
        (getconf("TEST_PAGE_NAME"), "Test2"),
    ],
)
@pytest.mark.gdrive_access
def test_ws_rename(manager: SpreadsheetManager, new_name: str, old_name: str):
    assert not manager.is_worksheet_exist(new_name)

    if old_name:
        assert manager.is_worksheet_exist(old_name)
        manager.rename_worksheet(new_name, old_name)
    else:
        assert manager.is_worksheet_exist(DEFAULT_WORKSHEET_NAME)
        manager.rename_worksheet(new_name)

    assert manager.is_worksheet_exist(new_name)
    assert not manager.is_worksheet_exist(old_name)
