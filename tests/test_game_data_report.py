from datetime import date, datetime
from pathlib import Path

from prometheus_client import CollectorRegistry
from telebot.types import CallbackQuery, Chat, Message, User

from config.config import getconf, reset_config
from db.access_group import AccessGroup, AccessGroupDB
from db.admins import Admin, AdminsDB
from db.database import Database
from pygsheets.exceptions import WorksheetNotFound

reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.user_data import UPDATED_AT_FIELDS, UserData
from reports.game_data import GameDataReport, USER_DATA_PAGE_NAME
from tg.admins import admins_main_menu
from tg.admins.clans import select_clan
from tg.admins import game_data as game_data_module
from tg.admins.game_data import export_game_data
from tg.metrics import ApplicationMetrics


class FakeWorksheet:
    def __init__(self):
        self.cleared = False
        self.values = None
        self.start = None
        self.extend = None
        self.cols = 26
        self.shown_dimensions = []
        self.frozen_rows = 0

    def clear(self):
        self.cleared = True

    def update_values(self, start, values, extend=False):
        self.start = start
        self.values = values
        self.extend = extend

    def show_dimensions(self, start, end=None, dimension="ROWS"):
        self.shown_dimensions.append((start, end, dimension))


class FakeSpreadsheet:
    def __init__(self, worksheet, exists=True):
        self.worksheet = worksheet
        self.exists = exists
        self.requested_worksheet = None
        self.added_worksheet = None
        self.url = "https://docs.google.test/report"

    def worksheet_by_title(self, worksheet_name):
        self.requested_worksheet = worksheet_name
        if not self.exists:
            raise WorksheetNotFound(worksheet_name)
        return self.worksheet

    def add_worksheet(self, worksheet_name):
        self.added_worksheet = worksheet_name
        return self.worksheet


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet
        self.opened_key = None

    def open_by_key(self, spreadsheet_key):
        self.opened_key = spreadsheet_key
        return self.spreadsheet


class FakeBot:
    def __init__(self):
        self.edits = []
        self.answers = []
        self.deleted_states = []

    def edit_message_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)


def make_callback(data="admins/game_data"):
    user = User(42, False, "Admin", username="admin")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def callback_data(markup):
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_report_replaces_google_worksheet_with_sqlite_snapshot(monkeypatch):
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet)
    client = FakeClient(spreadsheet)
    user = UserData(user_id=42, username="player", pets=7)
    user.mark_updated("pets", date(2026, 8, 2))
    users = [user]
    monkeypatch.setattr(
        "common.datetime_utils.now", lambda: datetime(2026, 8, 2, 12)
    )

    url = GameDataReport(client).export(users)

    assert client.opened_key == getconf("GAME_DATA_GTABLE_KEY")
    assert spreadsheet.requested_worksheet == USER_DATA_PAGE_NAME
    assert worksheet.cleared
    assert worksheet.start == "A1"
    expected_row = users[0].to_row()
    parameter_names = list(users[0].params())
    for update_field in UPDATED_AT_FIELDS.values():
        expected_row[parameter_names.index(update_field)] = "никогда"
    expected_row[parameter_names.index("pets_updated_on")] = (
        "сегодня (02.08.2026)"
    )
    assert worksheet.values == GameDataReport.HEADER + [expected_row]
    assert worksheet.extend
    assert worksheet.shown_dimensions == [(1, worksheet.cols, "COLUMNS")]
    assert worksheet.frozen_rows == 1
    assert url == "https://docs.google.test/report"


def test_report_creates_missing_worksheet():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet, exists=False)

    GameDataReport(FakeClient(spreadsheet)).export([])

    assert spreadsheet.added_worksheet == USER_DATA_PAGE_NAME
    assert worksheet.values == GameDataReport.HEADER


def test_admin_menu_contains_game_data_report(monkeypatch):
    monkeypatch.setattr(
        "tg.admins.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {
                "get_active_group": lambda _, user_id: AccessGroup(
                    -100123, "Test clan"
                ),
                "get_clans": lambda _, user_id: [
                    AccessGroup(-100123, "Test clan")
                ],
            },
        )(),
    )
    bot = FakeBot()

    admins_main_menu(make_callback("admins"), bot)

    markup = bot.edits[0][1]["reply_markup"]
    assert "admins/game_data" in callback_data(markup)
    assert bot.edits[0][0][0] == (
        "<b>Админ-панель</b>\nКлан: <b>Test clan</b>\n\nВыберите действие."
    )
    assert [button.text for row in markup.keyboard for button in row] == [
        "👥 Список игроков",
        "📣 Уведомления",
        "📤 Обновить Google Таблицу",
        "➕ Добавить клан",
        "✏️ Переименовать клан",
        "👥 Список администраторов",
        "➕ Добавить администраторов",
        "🗑 Удалить администратора",
        "⬅️ Назад в меню",
    ]


def test_admin_can_switch_active_clan(tmp_path, monkeypatch):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100001)
    admins.add_admin(Admin("admin", 42), -100002)
    monkeypatch.setattr("tg.admins.get_admins_db", lambda: admins)
    monkeypatch.setattr("tg.admins.clans.get_admins_db", lambda: admins)
    bot = FakeBot()

    admins_main_menu(make_callback("admins"), bot)
    assert "admins/clans" in callback_data(bot.edits[-1][1]["reply_markup"])

    select_clan(make_callback("admins/clans/-100002"), bot)

    assert admins.get_active_group(42) == AccessGroup(-100002, "Beta")
    assert "Клан: <b>Beta</b>" in bot.edits[-1][0][0]
    connection.close()


def test_game_data_callback_exports_and_shows_url(monkeypatch):
    users = [UserData(user_id=42, username="player")]
    exported = []

    class FakeReport:
        def export(self, report_users):
            exported.extend(report_users)
            return "https://docs.google.test/report"

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_user_data_db",
        lambda: type("Users", (), {"get_users": lambda _, clan_id: users})(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_active_admin_group",
        lambda user_id: AccessGroup(-100123, "Test clan"),
    )
    registry = CollectorRegistry()
    monkeypatch.setattr(
        game_data_module,
        "APPLICATION_METRICS",
        ApplicationMetrics(registry),
    )
    bot = FakeBot()

    export_game_data(make_callback(), bot)

    assert exported == users
    assert bot.edits[0][0][0] == "Формирую игровые данные…"
    markup = bot.edits[1][1]["reply_markup"]
    assert markup.keyboard[0][0].url == "https://docs.google.test/report"
    assert callback_data(markup) == ["admins"]
    assert registry.get_sample_value(
        "srm_reports_total",
        {"report": "game_data", "result": "completed"},
    ) == 1


def test_game_data_callback_reports_export_failure(monkeypatch):
    class BrokenReport:
        def export(self, _users):
            raise RuntimeError("Google unavailable")

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", BrokenReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_user_data_db",
        lambda: type("Users", (), {"get_users": lambda _, clan_id: []})(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_active_admin_group",
        lambda user_id: AccessGroup(-100123, "Test clan"),
    )
    bot = FakeBot()

    export_game_data(make_callback(), bot)

    assert bot.edits[0][0][0] == "Формирую игровые данные…"
    assert "Не удалось сформировать" in bot.edits[1][0][0]
    assert callback_data(bot.edits[1][1]["reply_markup"]) == ["admins"]
    assert bot.answers == []
