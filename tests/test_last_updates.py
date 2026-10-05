from datetime import date, datetime
from pathlib import Path
import re

from telebot.types import CallbackQuery, Chat, Message, User

from config.config import reset_config


reset_config(str(Path(__file__).parents[1] / "config" / "config_template.ini"))

from resources.clan_technologies import ClanTechnologies
from resources.user_data import UserData
from resources.war import WAR_STAGES, WarPointsCalculator
from tests.handler_context import clan_admin_context
from tg.admins.resource_status import (
    build_last_updates_report,
    build_players_report,
    confirm_remove_player,
    player_war_points,
    players,
    players_by_points,
    players_page,
    remove_player,
)
from tg.utils import format_points


def make_callback(data: str) -> CallbackQuery:
    user = User(42, False, "Requester", username="requester")
    message = Message(1, user, 0, Chat(42, "private"), "text", {}, None)
    return CallbackQuery("callback-1", user, data, "", None, message)


def callback_data(html: str) -> list[str]:
    return re.findall(r'<tg-button[^>]+data="([^"]+)"', html)


class FakeBot:
    def __init__(self):
        self.edits = []
        self.sent = []
        self.answers = []

    def edit_message_text(self, *args, **kwargs):
        rich_message = kwargs.get("rich_message")
        self.edits.append(rich_message.html if rich_message else args[0])

    def send_rich_message(self, chat_id, rich_message):
        self.sent.append((chat_id, rich_message.html))

    def answer_callback_query(self, *args, **kwargs):
        self.answers.append((args, kwargs))


class FakeUserDataDB:
    def __init__(self, users):
        self.users = list(users)
        self.detached = []

    def get_clan_users(self, clan_id):
        return list(self.users)

    def detach_account_from_clan(self, user_id, account_id):
        self.detached.append((user_id, account_id))
        self.users = [
            user for user in self.users if user.account_id.value != account_id
        ]


class FakeAccessGroupDB:
    def get_clan_technologies(self, group_id):
        return ClanTechnologies()


def test_last_updates_report_uses_latest_field_and_readable_age(monkeypatch):
    current = UserData(user_id=42, username="tester", tag="Лидер")
    current.mark_updated("mount_keys", date(2026, 8, 8))
    current.mark_updated("hammers", date(2026, 8, 12))
    yesterday = UserData(user_id=43, username="second")
    yesterday.mark_updated("pets", date(2026, 8, 13))
    never = UserData(user_id=44, username="new")
    monkeypatch.setattr(
        "common.datetime_utils.now", lambda: datetime(2026, 8, 14, 12)
    )

    report = build_last_updates_report([current, yesterday, never])

    assert "<h2>Последнее обновление ресурсов</h2>" in report
    assert "<aside>Всего аккаунтов<br><b>3</b></aside>" in report
    assert "tester (Лидер)</a><br><i>2 дня назад (12.08.2026)</i>" in report
    assert "second</a><br><i>вчера (13.08.2026)</i>" in report
    assert "new</a><br><i>никогда</i>" in report
    assert "tg://user?id=42" in report
    assert report.index("second</a>") < report.index("tester (")
    assert report.index("tester (") < report.index("new</a>")


def test_players_report_includes_points_actions_and_both_sort_orders(monkeypatch):
    recent = UserData(
        account_id=1,
        user_id=42,
        username="recent",
        tag="Recent",
        hammers=1,
    )
    recent.mark_updated("hammers", date(2026, 8, 14))
    high_score = UserData(
        account_id=2,
        user_id=43,
        username="fighter",
        tag="Fighter",
        hammers=10_000,
    )
    high_score.mark_updated("hammers", date(2026, 8, 13))
    monkeypatch.setattr(
        "common.datetime_utils.now", lambda: datetime(2026, 8, 14, 12)
    )
    calculator = WarPointsCalculator()

    by_updates = build_players_report([high_score, recent], calculator)
    by_points = build_players_report(
        [recent, high_score], calculator, sort="points"
    )

    high_score_points = calculator.calculate([high_score], WAR_STAGES).total
    assert by_updates.index("recent (Recent)</a>") < by_updates.index(
        "fighter (Fighter)</a>"
    )
    assert by_points.index("fighter (Fighter)</a>") < by_points.index(
        "recent (Recent)</a>"
    )
    assert f"Очки войны: {format_points(high_score_points)}" in by_points
    assert callback_data(by_updates) == [
        "admins/players/war/1/0/updates",
        "admins/players/remove/1/0/updates",
        "admins/players/war/2/0/updates",
        "admins/players/remove/2/0/updates",
    ]


def test_players_navigation_and_account_report(monkeypatch):
    account = UserData(
        account_id=7,
        user_id=77,
        username="player",
        tag="Hero",
        hammers=300,
    )
    database = FakeUserDataDB([account])
    monkeypatch.setattr(
        "tg.admins.resource_status.get_user_data_db", lambda: database
    )
    monkeypatch.setattr(
        "tg.admins.resource_status.get_access_group_db",
        lambda: FakeAccessGroupDB(),
    )
    bot = FakeBot()

    players(clan_admin_context(make_callback("admins/players"), bot))
    assert callback_data(bot.edits[-1])[-3:] == [
        "admins/players/points",
        "admins",
        "home",
    ]

    players_by_points(
        clan_admin_context(make_callback("admins/players/points"), bot)
    )
    assert callback_data(bot.edits[-1])[-3:] == [
        "admins/players",
        "admins",
        "home",
    ]

    player_war_points(
        clan_admin_context(
            make_callback("admins/players/war/7/0/points"), bot
        )
    )
    assert "<h2>Калькулятор очков войны</h2>" in bot.edits[-1]
    assert "Аккаунт: <b>Hero</b>" in bot.edits[-1]
    assert callback_data(bot.edits[-1]) == [
        "admins/players/page/0/points",
        "home",
    ]


def test_players_list_is_paginated_by_ten_accounts(monkeypatch):
    users = [
        UserData(
            account_id=index,
            user_id=100 + index,
            username=f"player-{index:02d}",
            tag=f"Hero {index:02d}",
        )
        for index in range(12)
    ]
    database = FakeUserDataDB(users)
    monkeypatch.setattr(
        "tg.admins.resource_status.get_user_data_db", lambda: database
    )
    monkeypatch.setattr(
        "tg.admins.resource_status.get_access_group_db",
        lambda: FakeAccessGroupDB(),
    )
    bot = FakeBot()

    players(clan_admin_context(make_callback("admins/players"), bot))

    first_page_buttons = callback_data(bot.edits[-1])
    assert len(
        [button for button in first_page_buttons if "/war/" in button]
    ) == 10
    assert first_page_buttons[-4:] == [
        "admins/players/page/1/updates",
        "admins/players/points",
        "admins",
        "home",
    ]

    players_page(
        clan_admin_context(
            make_callback("admins/players/page/1/updates"), bot
        )
    )

    second_page_buttons = callback_data(bot.edits[-1])
    assert len(
        [button for button in second_page_buttons if "/war/" in button]
    ) == 2
    assert second_page_buttons[-4:] == [
        "admins/players/page/0/updates",
        "admins/players/points",
        "admins",
        "home",
    ]


def test_remove_player_requires_confirmation_and_detaches_selected_account(
    monkeypatch,
):
    selected = UserData(
        account_id=7,
        user_id=77,
        username="player",
        tag="Hero",
    )
    other = UserData(
        account_id=8,
        user_id=88,
        username="other",
        tag="Other",
    )
    database = FakeUserDataDB([selected, other])
    monkeypatch.setattr(
        "tg.admins.resource_status.get_user_data_db", lambda: database
    )
    monkeypatch.setattr(
        "tg.admins.resource_status.get_access_group_db",
        lambda: FakeAccessGroupDB(),
    )
    bot = FakeBot()

    confirm_remove_player(
        clan_admin_context(
            make_callback("admins/players/remove/7/0/updates"), bot
        )
    )

    assert database.detached == []
    assert "Убрать аккаунт из клана?" in bot.edits[-1]
    assert callback_data(bot.edits[-1]) == [
        "admins/players/remove/confirm/7/0/updates",
        "admins/players/page/0/updates",
        "home",
    ]

    remove_player(
        clan_admin_context(
            make_callback("admins/players/remove/confirm/7/0/updates"), bot
        )
    )

    assert database.detached == [(77, 7)]
    assert "player (Hero)</a>" not in bot.edits[-1]
    assert "other (Other)</a>" in bot.edits[-1]
    assert bot.answers == [
        (("callback-1", "Игровой аккаунт убран из клана"), {})
    ]
