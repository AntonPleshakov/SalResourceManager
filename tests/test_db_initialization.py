from pathlib import Path
from types import SimpleNamespace

from config.config import reset_config

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from db.access_group import SETTINGS_HEADER, SETTINGS_WORKSHEET_NAME, AccessGroupDB
from db.admins import AdminsDB
from db.gapi.worksheet_manager import WorksheetManager
from db.user_data import LEGACY_V1_HEADER, UserDataDB
from db.war_stages import WarStagesDB
from resources.user_data import UserData
from resources.war import DEFAULT_WAR_STAGES


class FakeGoogleWorksheet:
    def __init__(self, values=None, frozen_rows=0):
        self.values = [list(row) for row in (values or [])]
        self.frozen_rows = frozen_rows
        self.rows = 100
        self.cols = 26
        self.title = "Test"
        self.spreadsheet = SimpleNamespace(title="Spreadsheet")
        self.update_calls = 0
        self.fetch_calls = 0

    def get_all_values(self, **_):
        self.fetch_calls += 1
        return [list(row) for row in self.values]

    def adjust_column_width(self, *_):
        pass

    def apply_format(self, *_):
        pass

    def clear(self, start, _end):
        if start == (1, 1):
            self.values = []
        else:
            self.values = self.values[: start[0] - 1]

    def update_values(self, start, values, extend=True):
        del extend
        self.update_calls += 1
        row_index = start[0] - 1
        self.values[row_index:] = [list(row) for row in values]


def test_ensure_header_initializes_an_empty_worksheet():
    worksheet = FakeGoogleWorksheet()
    manager = WorksheetManager(worksheet)

    manager.ensure_header([["First", "Second"]])

    assert worksheet.values == [["First", "Second"]]
    assert worksheet.frozen_rows == 1
    assert manager.get_all_values() == []
    assert worksheet.fetch_calls == 2


def test_ensure_header_preserves_existing_rows():
    worksheet = FakeGoogleWorksheet([["one", "1"]])
    manager = WorksheetManager(worksheet)

    manager.ensure_header([["Name", "Value"]])

    assert worksheet.values == [["Name", "Value"], ["one", "1"]]
    assert manager.get_all_values() == [["one", "1"]]


def test_ensure_header_does_not_duplicate_an_unfrozen_header():
    header = [["Name", "Value"]]
    worksheet = FakeGoogleWorksheet(header + [["one", "1"]])
    manager = WorksheetManager(worksheet)

    manager.ensure_header(header)

    assert worksheet.values == header + [["one", "1"]]
    assert worksheet.update_calls == 0
    assert manager.get_all_values() == [["one", "1"]]
    assert worksheet.fetch_calls == 1


class FakeWorksheetManager:
    def __init__(self, rows=None):
        self.rows = [list(row) for row in (rows or [])]
        self.header = None
        self.hidden_columns = []
        self.update_calls = 0
        self.fetch_calls = 0

    def ensure_header(self, header):
        self.header = header

    def get_header(self):
        return self.header or []

    def set_header(self, header):
        self.header = header

    def hide_column(self, column):
        self.hidden_columns.append(column)

    def fetch(self):
        self.fetch_calls += 1

    def get_all_values(self):
        return self.rows

    def update_values(self, rows):
        self.update_calls += 1
        self.rows = [list(row) for row in rows]


class FakeSpreadsheet:
    def __init__(self, manager, worksheet_exists=False):
        self.manager = manager
        self.worksheet_exists = worksheet_exists
        self.added = []
        self.opened = []

    def is_worksheet_exist(self, name):
        return self.worksheet_exists

    def add_worksheet(self, name):
        self.added.append(name)
        return self.manager

    def get_worksheet(self, name):
        self.opened.append(name)
        return self.manager

    def get_url(self):
        return "https://docs.google.com/spreadsheets/d/example"


def patch_spreadsheet(monkeypatch, module, spreadsheet):
    monkeypatch.setattr(
        module,
        "GSheetsManager",
        lambda: SimpleNamespace(open=lambda _spreadsheet_id: spreadsheet),
    )


def test_admins_db_creates_worksheet_and_header(monkeypatch):
    import db.admins as admins

    manager = FakeWorksheetManager()
    spreadsheet = FakeSpreadsheet(manager)
    patch_spreadsheet(monkeypatch, admins, spreadsheet)

    AdminsDB()

    assert spreadsheet.added == ["Admins"]
    assert manager.header == AdminsDB.HEADER
    assert manager.fetch_calls == 0


def test_access_group_db_initializes_existing_empty_worksheet(monkeypatch):
    import db.access_group as access_group

    manager = FakeWorksheetManager()
    spreadsheet = FakeSpreadsheet(manager, worksheet_exists=True)
    patch_spreadsheet(monkeypatch, access_group, spreadsheet)

    AccessGroupDB()

    assert spreadsheet.opened == [SETTINGS_WORKSHEET_NAME]
    assert manager.header == SETTINGS_HEADER
    assert manager.fetch_calls == 0


def test_user_data_db_initializes_existing_empty_worksheet(monkeypatch):
    import db.user_data as user_data

    manager = FakeWorksheetManager()
    spreadsheet = FakeSpreadsheet(manager, worksheet_exists=True)
    patch_spreadsheet(monkeypatch, user_data, spreadsheet)

    database = UserDataDB.connect()

    assert database.get_users() == []
    assert manager.header == [UserData().params_views()]
    assert manager.fetch_calls == 0
    assert manager.hidden_columns == [
        index
        for index, name in enumerate(UserData().params())
        if name.endswith("_updated_on")
    ]


def test_user_data_db_migrates_legacy_rows_and_removes_gems(monkeypatch):
    legacy_row = [
        "42",
        "tester",
        "1000",
        "2000",
        "3",
        "4000",
        "999",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
    ]
    manager = FakeWorksheetManager([legacy_row])
    manager.header = [LEGACY_V1_HEADER]
    spreadsheet = FakeSpreadsheet(manager, worksheet_exists=True)
    import db.user_data as user_data

    patch_spreadsheet(monkeypatch, user_data, spreadsheet)

    database = UserDataDB.connect()
    user = database.get_user(42)

    assert manager.header == UserDataDB.HEADER
    assert len(manager.rows[0]) == len(UserDataDB.HEADER[0])
    assert "Гемы" not in manager.header[0]
    assert "Питомцы и яйца" in manager.header[0]
    assert manager.header[0].index("Тег") == manager.header[0].index("Пользователь") + 1
    assert user.mount_keys.value == 1000
    assert user.pets.value == 5
    assert user.forge_level.value == 7
    assert user.tag.value == ""
    assert user.get_updated_on("pets") is None




def test_war_stages_db_initializes_existing_empty_worksheet(monkeypatch):
    import db.war_stages as war_stages

    manager = FakeWorksheetManager()
    spreadsheet = FakeSpreadsheet(manager, worksheet_exists=True)
    patch_spreadsheet(monkeypatch, war_stages, spreadsheet)

    database = WarStagesDB.connect()

    assert manager.header == WarStagesDB.HEADER
    assert manager.rows == WarStagesDB._stages_to_rows(DEFAULT_WAR_STAGES)
    assert database.get_stages() == DEFAULT_WAR_STAGES
    assert manager.fetch_calls == 0


def test_war_stages_db_preserves_existing_rows(monkeypatch):
    import db.war_stages as war_stages

    rows = WarStagesDB._stages_to_rows(DEFAULT_WAR_STAGES)
    manager = FakeWorksheetManager(rows)
    spreadsheet = FakeSpreadsheet(manager, worksheet_exists=True)
    patch_spreadsheet(monkeypatch, war_stages, spreadsheet)

    WarStagesDB.connect()

    assert manager.rows == rows
    assert manager.update_calls == 0
