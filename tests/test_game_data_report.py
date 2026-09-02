from datetime import date, datetime, timezone
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
from reports.game_data import (
    GameDataReport,
    GoogleAccessProposal,
    USER_DATA_PAGE_NAME,
)
from tg.admins import admins_main_menu
from tg.admins.clans import select_clan
from tg.admins import game_data as game_data_module
from tg.admins.game_data import (
    build_game_data_message,
    check_google_access_request,
    connect_google_account,
    export_game_data,
    show_game_data,
)
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
        self.id = "spreadsheet-123"
        self.worksheet = worksheet
        self.exists = exists
        self.requested_worksheet = None
        self.added_worksheet = None
        self.url = "https://docs.google.test/report"
        self.permissions = []
        self.shares = []
        self.removed_permissions = []

    def worksheet_by_title(self, worksheet_name):
        self.requested_worksheet = worksheet_name
        if not self.exists:
            raise WorksheetNotFound(worksheet_name)
        return self.worksheet

    def add_worksheet(self, worksheet_name):
        self.added_worksheet = worksheet_name
        return self.worksheet

    def share(self, email, **kwargs):
        self.shares.append((email, kwargs))

    def remove_permission(self, email, permission_id=None):
        self.removed_permissions.append((email, permission_id))


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet
        self.opened_key = None
        self.created = []

    def open_by_key(self, spreadsheet_key):
        self.opened_key = spreadsheet_key
        return self.spreadsheet

    def create(self, title, folder):
        self.created.append((title, folder))
        return self.spreadsheet


class FakeGroups:
    def __init__(self, spreadsheet_id="spreadsheet-123"):
        self.spreadsheet_id = spreadsheet_id

    def get_spreadsheet_id(self, group_id):
        return self.spreadsheet_id

    def set_spreadsheet_id(self, group_id, spreadsheet_id):
        self.spreadsheet_id = spreadsheet_id


class FakeHTTPResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}
        self.checked = False

    def raise_for_status(self):
        self.checked = True

    def json(self):
        return self.payload


class FakeDriveSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.gets = []
        self.posts = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeHTTPResponse()


class FakeBot:
    def __init__(self):
        self.data = {}
        self.edits = []
        self.markup_edits = []
        self.answers = []
        self.deleted_states = []
        self.states = []
        self.sent = []
        self.replies = []

    def edit_message_text(self, *args, **kwargs):
        self.edits.append((args, kwargs))

    def edit_message_reply_markup(self, *args, **kwargs):
        self.markup_edits.append((args, kwargs))

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))

    def delete_state(self, user_id):
        self.deleted_states.append(user_id)

    def set_state(self, user_id, state):
        self.states.append((user_id, state))

    def add_data(self, user_id, **kwargs):
        self.data.update(kwargs)

    def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))

    def reply_to(self, message, text):
        self.replies.append((message, text))

    def get_chat_member(self, group_id, user_id):
        return type("Member", (), {"status": "member"})()


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

    url = GameDataReport(client, FakeGroups()).export(
        -100123, "Test clan", "admin@example.com", users
    )

    assert client.opened_key == "spreadsheet-123"
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
    assert spreadsheet.shares == [
        (
            "admin@example.com",
            {
                "role": "reader",
                "type": "user",
                "sendNotificationEmail": False,
            },
        )
    ]
    assert url == "https://docs.google.test/report"


def test_report_creates_missing_worksheet():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet, exists=False)

    GameDataReport(FakeClient(spreadsheet), FakeGroups()).export(
        -100123, "Test clan", "admin@example.com", []
    )

    assert spreadsheet.added_worksheet == USER_DATA_PAGE_NAME
    assert worksheet.values == GameDataReport.HEADER


def test_report_creates_a_clan_spreadsheet_in_configured_folder():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet)
    client = FakeClient(spreadsheet)
    groups = FakeGroups(spreadsheet_id=None)

    GameDataReport(client, groups).export(
        -100123, "Test clan", "admin@example.com", []
    )

    assert client.created == [
        ("Forge Master — Test clan", getconf("GAME_DATA_GFOLDER_KEY"))
    ]
    assert groups.spreadsheet_id == spreadsheet.id


def test_report_prepares_closed_clan_spreadsheet_without_exporting_data():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet)

    url = GameDataReport(
        FakeClient(spreadsheet), FakeGroups()
    ).prepare(-100123, "Test clan")

    assert url == spreadsheet.url
    assert spreadsheet.shares == []
    assert worksheet.values is None


def test_report_lists_only_direct_recent_access_proposals():
    drive = FakeDriveSession(
        [
            FakeHTTPResponse(
                {
                    "accessProposals": [
                        {
                            "proposalId": "old",
                            "requesterEmailAddress": "old@example.com",
                            "recipientEmailAddress": "old@example.com",
                            "createTime": "2026-09-03T09:59:00Z",
                        },
                        {
                            "proposalId": "delegated",
                            "requesterEmailAddress": "one@example.com",
                            "recipientEmailAddress": "two@example.com",
                            "createTime": "2026-09-03T10:01:00Z",
                        },
                        {
                            "proposalId": "current",
                            "requesterEmailAddress": "Admin@Example.COM",
                            "recipientEmailAddress": "Admin@Example.COM",
                            "createTime": "2026-09-03T10:01:00Z",
                        },
                    ]
                }
            )
        ]
    )
    created_after = int(datetime(2026, 9, 3, 10, tzinfo=timezone.utc).timestamp())

    proposals = GameDataReport(
        FakeClient(FakeSpreadsheet(FakeWorksheet())),
        FakeGroups(),
        drive,
    ).get_access_proposals(-100123, created_after)

    assert proposals == [
        GoogleAccessProposal("current", "admin@example.com")
    ]
    assert drive.gets[0][0].endswith(
        "/spreadsheet-123/accessproposals"
    )


def test_report_approves_access_proposal_as_reader_only():
    drive = FakeDriveSession()

    GameDataReport(
        FakeClient(FakeSpreadsheet(FakeWorksheet())),
        FakeGroups(),
        drive,
    ).approve_access(-100123, "proposal-1")

    assert drive.posts[0][0].endswith(
        "/spreadsheet-123/accessproposals/proposal-1:resolve"
    )
    assert drive.posts[0][1]["json"] == {
        "role": ["reader"],
        "action": "ACCEPT",
        "sendNotification": False,
    }


def test_report_replaces_existing_writer_permission_with_reader():
    worksheet = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(worksheet)
    spreadsheet.permissions = [
        {
            "id": "permission-1",
            "emailAddress": "admin@example.com",
            "type": "user",
            "role": "writer",
        }
    ]

    GameDataReport(FakeClient(spreadsheet), FakeGroups()).export(
        -100123, "Test clan", "admin@example.com", []
    )

    assert spreadsheet.removed_permissions == [
        ("admin@example.com", "permission-1")
    ]
    assert spreadsheet.shares[0][1]["role"] == "reader"


def test_report_revokes_case_insensitive_permission_from_clan_spreadsheet():
    spreadsheet = FakeSpreadsheet(FakeWorksheet())
    spreadsheet.permissions = [
        {
            "id": "permission-1",
            "emailAddress": "Admin@Example.com",
            "type": "user",
            "role": "reader",
        },
        {
            "id": "permission-2",
            "emailAddress": "other@example.com",
            "type": "user",
            "role": "reader",
        },
    ]
    client = FakeClient(spreadsheet)

    GameDataReport(client, FakeGroups()).revoke_access(
        -100123, "admin@example.com"
    )

    assert client.opened_key == "spreadsheet-123"
    assert spreadsheet.removed_permissions == [
        ("admin@example.com", "permission-1")
    ]


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
                "is_clan_admin": lambda _, user_id, group_id: True,
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
        "📊 Игровые данные",
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


def test_admin_menu_requires_selection_after_active_access_is_revoked(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    groups.add_group(-100002, "Beta")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100001)
    admins.add_admin(Admin("admin", 42), -100002)
    admins.select_group(42, -100002)
    admins.del_clan_admin(42, -100002)
    monkeypatch.setattr("tg.admins.get_admins_db", lambda: admins)
    bot = FakeBot()

    admins_main_menu(make_callback("admins"), bot)

    buttons = callback_data(bot.edits[-1][1]["reply_markup"])
    assert "admins/clans" in buttons
    assert "admins/game_data" not in buttons
    assert "Выберите клан для административных действий" in bot.edits[-1][0][0]
    connection.close()


def test_departed_admin_menu_revokes_acl_and_hides_admin_actions(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100001, "Alpha")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100001)
    monkeypatch.setattr("tg.admins.get_admins_db", lambda: admins)

    class DepartedBot(FakeBot):
        def get_chat_member(self, group_id, user_id):
            return type("Member", (), {"status": "left"})()

    bot = DepartedBot()

    admins_main_menu(make_callback("admins"), bot)

    buttons = callback_data(bot.edits[-1][1]["reply_markup"])
    assert buttons == ["home"]
    assert "нет актуальных прав администратора" in bot.edits[-1][0][0]
    assert not admins.has_admin_access(42)
    connection.close()


def test_game_data_rich_message_contains_native_tables_and_escaped_values():
    user = UserData(
        account_id=7,
        user_id=42,
        username="player<&",
        tag="Leader",
        pets=9,
    )

    message = build_game_data_message("Clan <One>", [user])

    assert "<h2>Игровые данные</h2>" in message.html
    assert "Clan &lt;One&gt;" in message.html
    assert "player&lt;&amp;" in message.html
    assert message.html.count("<table bordered striped compact>") == 2
    assert "Поля 1 из 2" in message.html
    assert "Поля 2 из 2" in message.html
    assert message.skip_entity_detection


def test_game_data_rich_message_limits_large_preview():
    users = [
        UserData(
            account_id=index,
            user_id=index,
            username=f"player-{index}",
            tag="Очень длинное игровое имя",
        )
        for index in range(300)
    ]

    message = build_game_data_message("Large clan", users)

    assert len(message.html.encode("utf-8")) <= 30_000
    assert "Показано" in message.html
    assert "из 300 аккаунтов" in message.html
    assert "В Google экспортируются все данные" in message.html


def test_game_data_callback_shows_table_before_export(monkeypatch):
    users = [UserData(user_id=42, username="player")]
    monkeypatch.setattr(
        "tg.admins.game_data.get_user_data_db",
        lambda: type(
            "Users",
            (),
            {
                "get_clan_users": lambda _, clan_id: users,
                "get_clan_user_ids": lambda _, clan_id: [],
            },
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_active_admin_group",
        lambda bot, user_id: AccessGroup(-100123, "Test clan"),
    )
    bot = FakeBot()

    show_game_data(make_callback(), bot)

    assert bot.edits[0][0] == ()
    rich_message = bot.edits[0][1]["rich_message"]
    assert "<table bordered striped compact>" in rich_message.html
    assert "player" in rich_message.html
    assert callback_data(bot.edits[0][1]["reply_markup"]) == [
        "admins/game_data/google/-100123",
        "admins/game_data/google/connect/-100123",
        "admins",
    ]


def test_google_export_callback_exports_and_shows_url(monkeypatch):
    users = [UserData(user_id=42, username="player")]
    exported = []

    class FakeReport:
        def export(self, group_id, clan_title, google_email, report_users):
            assert (group_id, clan_title, google_email) == (
                -100123,
                "Test clan",
                "admin@example.com",
            )
            exported.extend(report_users)
            return "https://docs.google.test/report"

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_user_data_db",
        lambda: type(
            "Users",
            (),
            {
                "get_clan_users": lambda _, clan_id: users,
                "get_clan_user_ids": lambda _, clan_id: [],
            },
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_access_group_db",
        lambda: type(
            "Groups",
            (),
            {"get_group": lambda _, group_id: AccessGroup(group_id, "Test clan")},
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {
                "is_clan_admin": lambda _, user_id, group_id: True,
                "get_clan_admin_google_email": (
                    lambda _, user_id, group_id: "admin@example.com"
                ),
            },
        )(),
    )
    registry = CollectorRegistry()
    monkeypatch.setattr(
        game_data_module,
        "APPLICATION_METRICS",
        ApplicationMetrics(registry),
    )
    bot = FakeBot()

    export_game_data(make_callback("admins/game_data/google/-100123"), bot)

    assert exported == users
    markup = bot.markup_edits[0][1]["reply_markup"]
    assert markup.keyboard[0][0].url == "https://docs.google.test/report"
    assert callback_data(markup) == ["admins/game_data", "admins"]
    assert bot.answers[0][0] == (
        "callback-1",
        "Данные экспортированы в Google.",
    )
    assert registry.get_sample_value(
        "srm_reports_total",
        {"report": "game_data", "result": "completed"},
    ) == 1


def test_google_export_prepares_table_and_requests_drive_access(monkeypatch):
    exported = []

    class FakeReport:
        def prepare(self, group_id, clan_title):
            assert (group_id, clan_title) == (-100123, "Test clan")
            return "https://docs.google.test/restricted-report"

        def export(self, *args):
            exported.append(args)

    requested = []
    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_access_group_db",
        lambda: type(
            "Groups",
            (),
            {"get_group": lambda _, group_id: AccessGroup(group_id, "Test clan")},
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {
                "is_clan_admin": lambda _, user_id, group_id: True,
                "get_clan_admin_google_email": lambda _, user_id, group_id: None,
                "start_google_access_request": (
                    lambda _, user_id, group_id, requested_at: requested.append(
                        (user_id, group_id, requested_at)
                    )
                ),
            },
        )(),
    )
    bot = FakeBot()

    export_game_data(make_callback("admins/game_data/google/-100123"), bot)

    assert exported == []
    assert requested[0][0:2] == (42, -100123)
    markup = bot.edits[-1][1]["reply_markup"]
    assert markup.keyboard[0][0].url == (
        "https://docs.google.test/restricted-report"
    )
    assert callback_data(markup) == [
        "admins/game_data/google/check/-100123",
        "admins/game_data",
    ]
    assert "Запросить доступ" in bot.edits[-1][0][0]


def test_existing_email_can_start_explicit_account_change(monkeypatch):
    class FakeReport:
        def prepare(self, group_id, clan_title):
            return "https://docs.google.test/restricted-report"

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_access_group_db",
        lambda: type(
            "Groups",
            (),
            {"get_group": lambda _, group_id: AccessGroup(group_id, "Test clan")},
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {
                "is_clan_admin": lambda _, user_id, group_id: True,
                "start_google_access_request": lambda *args: None,
            },
        )(),
    )
    bot = FakeBot()

    connect_google_account(
        make_callback("admins/game_data/google/connect/-100123"), bot
    )

    assert bot.edits[-1][1]["reply_markup"].keyboard[0][0].url == (
        "https://docs.google.test/restricted-report"
    )


def test_drive_access_request_saves_email_approves_reader_and_exports(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Test clan")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100123)
    admins.start_google_access_request(42, -100123, 1_000)
    exported = []
    approved = []

    class FakeReport:
        def get_access_proposals(self, group_id, created_after):
            assert (group_id, created_after) == (-100123, 1_000)
            return [GoogleAccessProposal("proposal-1", "admin@example.com")]

        def approve_access(self, group_id, proposal_id):
            assert admins.get_clan_admin_google_email(42, group_id) == (
                "admin@example.com"
            )
            approved.append((group_id, proposal_id))

        def revoke_access(self, group_id, google_email):
            raise AssertionError("There is no previous email")

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data._export_group_data",
        lambda bot, user_id, group_id, google_email: (
            exported.append((user_id, group_id, google_email))
            or "https://docs.google.test/clan-report"
        ),
    )
    monkeypatch.setattr("tg.admins.game_data.get_admins_db", lambda: admins)
    bot = FakeBot()

    check_google_access_request(
        make_callback("admins/game_data/google/check/-100123"), bot
    )

    assert admins.get_clan_admin_google_email(42, -100123) == (
        "admin@example.com"
    )
    assert admins.get_google_access_requested_at(42, -100123) is None
    assert approved == [(-100123, "proposal-1")]
    assert exported == [
        (
            42,
            -100123,
            "admin@example.com",
        )
    ]
    assert bot.markup_edits[-1][1]["reply_markup"].keyboard[0][0].url == (
        "https://docs.google.test/clan-report"
    )
    connection.close()


def test_drive_request_for_new_email_revokes_previous_access_first(
    tmp_path, monkeypatch
):
    connection = Database(tmp_path / "database.db")
    groups = AccessGroupDB(connection)
    groups.add_group(-100123, "Test clan")
    admins = AdminsDB(connection)
    admins.add_admin(Admin("admin", 42), -100123)
    admins.set_clan_admin_google_email(42, -100123, "old@example.com")
    admins.start_google_access_request(42, -100123, 1_000)
    revoked = []

    class FakeReport:
        def get_access_proposals(self, group_id, created_after):
            return [GoogleAccessProposal("proposal-1", "new@example.com")]

        def revoke_access(self, group_id, google_email):
            assert admins.get_clan_admin_google_email(42, group_id) == (
                "old@example.com"
            )
            revoked.append((group_id, google_email))

        def approve_access(self, group_id, proposal_id):
            return None

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr("tg.admins.game_data.get_admins_db", lambda: admins)
    monkeypatch.setattr(
        "tg.admins.game_data._export_group_data",
        lambda *args: "https://docs.google.test/clan-report",
    )

    check_google_access_request(
        make_callback("admins/game_data/google/check/-100123"), FakeBot()
    )

    assert revoked == [(-100123, "old@example.com")]
    assert admins.get_clan_admin_google_email(42, -100123) == (
        "new@example.com"
    )
    connection.close()


def test_google_export_callback_reports_failure(monkeypatch):
    class BrokenReport:
        def export(self, group_id, clan_title, google_email, users):
            raise RuntimeError("Google unavailable")

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", BrokenReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_user_data_db",
        lambda: type(
            "Users", (), {"get_clan_users": lambda _, clan_id: []}
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_access_group_db",
        lambda: type(
            "Groups",
            (),
            {"get_group": lambda _, group_id: AccessGroup(group_id, "Test clan")},
        )(),
    )
    monkeypatch.setattr(
        "tg.admins.game_data.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {
                "is_clan_admin": lambda _, user_id, group_id: True,
                "get_clan_admin_google_email": (
                    lambda _, user_id, group_id: "admin@example.com"
                ),
            },
        )(),
    )
    bot = FakeBot()

    export_game_data(make_callback("admins/game_data/google/-100123"), bot)

    assert bot.markup_edits == []
    assert bot.answers[0][0][0] == "callback-1"
    assert "Не удалось экспортировать" in bot.answers[0][0][1]
    assert bot.answers[0][1]["show_alert"]


def test_google_export_rechecks_access_to_pinned_clan(monkeypatch):
    exported = []

    class FakeReport:
        def export(self, group_id, clan_title, google_email, users):
            exported.extend(users)
            return "https://docs.google.test/report"

    monkeypatch.setattr("tg.admins.game_data.GameDataReport", FakeReport)
    monkeypatch.setattr(
        "tg.admins.game_data.get_admins_db",
        lambda: type(
            "Admins",
            (),
            {"is_clan_admin": lambda _, user_id, group_id: False},
        )(),
    )
    bot = FakeBot()

    export_game_data(
        make_callback("admins/game_data/google/-100123"), bot
    )

    assert exported == []
    assert bot.markup_edits == []
    assert bot.answers[-1][0][1] == (
        "Нет прав администратора выбранного клана."
    )
    assert bot.answers[-1][1]["show_alert"] is True
