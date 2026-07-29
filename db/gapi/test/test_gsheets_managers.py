import time

import pytest

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager


@pytest.fixture
def manager():
    return GSheetsManager()


@pytest.mark.gdrive_access
@pytest.mark.slow
def test_sheet_creation(manager: GSheetsManager):
    new_ss = "test"
    assert not any(new_ss == ss.name for ss in manager.get_spreadsheets())

    # Create a spreadsheet
    manager.create(new_ss)
    cnt = 0
    while not any(new_ss == ss.name for ss in manager.get_spreadsheets()) and (
        cnt < 20
    ):
        time.sleep(0.1)
        cnt += 1
    assert cnt < 20
    assert any(new_ss == ss.name for ss in manager.get_spreadsheets())

    # Delete the spreadsheet
    manager.delete(new_ss)
    assert not any(new_ss == ss.name for ss in manager.get_spreadsheets())


@pytest.mark.gdrive_access
def test_sheet_open(manager: GSheetsManager):
    ss_name = getconf("TEST_GTABLE_KEY")
    ws_name = getconf("TEST_PAGE_NAME")

    ss = manager.open(ss_name)
    worksheets = ss._ss.worksheets()
    assert any(ws_name == ws.title for ws in worksheets)
