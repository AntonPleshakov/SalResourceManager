from contextlib import nullcontext
import re
from types import SimpleNamespace

import pytest

from resources.technology_badges import matches_technology_filter
from resources.user_data import UserData
from tests.handler_context import clan_admin_context
from tests.test_war_menu import FakeBot, FakeUserDataDB, make_callback, rich_callback_data
from tg.admins.common import AdminAccessError
from tg.war import top_actions
from tg.war.public import clan_war_top


class TopBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.data = {}
        self.states = []
        self.callbacks = []
        self.messages = []
        self.failed_ids = set()

    def retrieve_data(self, user_id):
        return nullcontext(self.data)

    def set_state(self, user_id, state):
        self.states.append(state)

    def add_data(self, user_id, **data):
        self.data.update(data)

    def delete_state(self, user_id):
        super().delete_state(user_id)
        self.data.clear()

    def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        if chat_id in self.failed_ids:
            raise RuntimeError("Bot blocked")
        self.sent.append((chat_id, text, reply_markup))

    def register_callback_query_handler(self, handler, **filters):
        self.callbacks.append((handler, filters))

    def register_message_handler(self, handler, **filters):
        self.messages.append((handler, filters))


def install_users(monkeypatch, users):
    database = FakeUserDataDB(UserData(user_id=42, account_id=100))
    database.get_clan_users = lambda clan_id: users if clan_id == -100123 else []
    monkeypatch.setattr("tg.war.get_user_data_db", lambda: database)
    monkeypatch.setattr(top_actions, "get_user_data_db", lambda: database)


def install_access(monkeypatch, allowed):
    admins = SimpleNamespace(get_clans=lambda user_id: [SimpleNamespace(group_id=-100123, title="Clan")])
    monkeypatch.setattr("db.initializer.get_admins_db", lambda: admins)

    def check_access(bot, user_id, clan_id, admins=None):
        if not allowed or clan_id != -100123:
            raise AdminAccessError("Нет доступа")

    monkeypatch.setattr("tg.admins.common.require_admin_access", check_access)
    monkeypatch.setattr(top_actions, "require_admin_access", check_access)


def invoke_callback(bot, data):
    if not bot.callbacks:
        top_actions.register_handlers(bot)
    handler, filters = next(
        (handler, filters) for handler, filters in bot.callbacks
        if re.fullmatch(filters["button"], data)
    )
    handler(make_callback(data=data), bot)


@pytest.mark.parametrize(
    "technology, values, expected",
    [
        ("any", {}, True),
        ("skills", {"skill_summon_cost": 25}, True),
        ("mounts", {"mount_summon_cost": 25, "extra_mount_chance": 49}, False),
        ("mounts", {"mount_summon_cost": 24, "extra_mount_chance": 50}, False),
        ("mounts", {"mount_summon_cost": 25, "extra_mount_chance": 50}, True),
        ("pets", {"extra_egg_chance": 50}, True),
        ("all", {"skill_summon_cost": 25, "extra_egg_chance": 50}, False),
        ("all", {"skill_summon_cost": 25, "extra_egg_chance": 50,
                 "mount_summon_cost": 25, "extra_mount_chance": 50}, True),
    ],
)
def test_filter_uses_completed_technologies(technology, values, expected):
    assert matches_technology_filter(UserData(**values), technology) is expected


@pytest.mark.parametrize("is_admin", [True, False])
def test_top_filters_before_pagination_and_limits_admin_actions(monkeypatch, is_admin):
    users = [UserData(user_id=index, account_id=index, tag=f"max-{index}", skill_summon_cost=25)
             for index in range(1, 22)]
    users.insert(0, UserData(user_id=99, account_id=99, tag="excluded", hammers=100))
    install_users(monkeypatch, users)
    install_access(monkeypatch, is_admin)
    bot = TopBot()

    clan_war_top(make_callback(data="war_top/skills/0"), bot)
    html = bot.edited[-1][0]
    callbacks = rich_callback_data(html)
    assert "excluded" not in html
    assert "Аккаунтов: 21" in html
    assert "war_top/skills/1" in callbacks
    assert "war_top_filters/skills" in callbacks
    assert ("war_top_copy/-100123/skills" in callbacks) is is_admin
    assert ("war_top_message/-100123/skills" in callbacks) is is_admin

    clan_war_top(make_callback(data="war_top/skills/1"), bot)
    assert "war_top/skills/0" in rich_callback_data(bot.edited[-1][0])
    assert "war_top/skills/2" not in rich_callback_data(bot.edited[-1][0])


def test_filter_menu_offers_reset_and_all_technology_groups():
    bot = TopBot()
    top_actions.top_filters(make_callback(data="war_top_filters/pets"), bot)
    callbacks = rich_callback_data(bot.edited[-1][0])
    for technology in ("any", "skills", "mounts", "pets", "all"):
        assert f"war_top/{technology}/0" in callbacks


def test_empty_filter_has_no_admin_actions(monkeypatch):
    install_users(monkeypatch, [UserData(user_id=1)])
    install_access(monkeypatch, True)
    bot = TopBot()
    clan_war_top(make_callback(data="war_top/all/0"), bot)
    html = bot.edited[-1][0]
    assert "По этому фильтру игроков нет" in html
    assert "war_top_copy" not in html
    assert "war_top_message" not in html


def test_copy_includes_all_pages_without_unmatched_or_empty_tags(monkeypatch):
    users = [UserData(user_id=index, account_id=index, tag=f"Игрок <{index:02d}>", extra_egg_chance=50)
             for index in range(35)]
    users.extend([
        UserData(user_id=80, tag="excluded"),
        UserData(user_id=81, tag="", extra_egg_chance=50),
        UserData(user_id=82, tag=users[0].tag.value, extra_egg_chance=50),
    ])
    install_users(monkeypatch, users)
    install_access(monkeypatch, True)
    bot = TopBot()

    invoke_callback(bot, "war_top_copy/-100123/pets")

    copied = [markup.keyboard[0][0].copy_text.text for _, _, markup in bot.sent]
    assert all(0 < len(chunk) <= 256 for chunk in copied)
    assert "\n".join(copied).splitlines() == [user.tag.value for user in users[:35]]
    assert all(chat_id == 42 for chat_id, _, _ in bot.sent)
    assert "&lt;00&gt;" in bot.sent[0][1]


@pytest.mark.parametrize("action", ["copy", "message"])
def test_forged_admin_callbacks_are_denied(monkeypatch, action):
    install_access(monkeypatch, False)
    bot = TopBot()
    invoke_callback(bot, f"war_top_{action}/-100123/all")
    assert not bot.sent
    assert not bot.states
    assert bot.answers[-1][1]["show_alert"] is True


def test_message_rechecks_audience_deduplicates_users_and_cannot_replay(monkeypatch):
    users = [UserData(user_id=index, account_id=index, skill_summon_cost=25)
             for index in range(1, 23)]
    users.append(UserData(user_id=1, account_id=50, skill_summon_cost=25))
    install_users(monkeypatch, users)
    install_access(monkeypatch, True)
    bot = TopBot()
    invoke_callback(bot, "war_top_message/-100123/skills")
    assert not bot.sent

    message = make_callback().message
    message.text = "Привет <клан> & друзья"
    top_actions.receive_top_message(clan_admin_context(message, bot))
    preview = bot.sent[-1][1]
    assert "Получателей: 22" in preview
    assert "Привет &lt;клан&gt; &amp; друзья" in preview
    confirm = next(value for value in rich_callback_data(preview) if value.startswith("war_top_send/"))
    bot.sent.clear()
    # One player left the clan, another no longer meets the filter, and a new one joined.
    users[:] = [user for user in users if user.user_id.value != 2]
    users[1].skill_summon_cost.value = 24
    users.append(UserData(user_id=90, account_id=90, skill_summon_cost=25))
    bot.failed_ids.add(4)

    invoke_callback(bot, confirm)

    recipients = [chat_id for chat_id, _, _ in bot.sent]
    assert set(recipients) == set(range(1, 23)) - {2, 3, 4}
    assert recipients.count(1) == 1
    assert all("Привет &lt;клан&gt; &amp; друзья" in text for _, text, _ in bot.sent)
    assert "Доставлено: 19. Ошибок: 1" in bot.edited[-1][0]
    invoke_callback(bot, confirm)
    assert len(bot.sent) == 19


def test_revoked_access_blocks_message_confirmation(monkeypatch):
    install_users(monkeypatch, [UserData(user_id=1, account_id=1, extra_egg_chance=50)])
    install_access(monkeypatch, True)
    bot = TopBot()
    invoke_callback(bot, "war_top_message/-100123/pets")
    message = make_callback().message
    message.text = "Привет"
    top_actions.receive_top_message(clan_admin_context(message, bot))
    confirm = next(value for value in rich_callback_data(bot.sent[-1][1]) if value.startswith("war_top_send/"))
    bot.sent.clear()
    install_access(monkeypatch, False)

    invoke_callback(bot, confirm)

    assert not bot.sent
    assert not bot.data
    assert bot.answers[-1][1]["show_alert"] is True


def test_return_to_top_cancels_draft(monkeypatch):
    install_users(monkeypatch, [])
    bot = TopBot()
    bot.data.update(top_draft=("old", "text", "admin"), top_clan_id=-100123)
    clan_war_top(make_callback(data="war_top/pets/0"), bot)
    assert not bot.data


@pytest.mark.parametrize("text", ["   ", "a" * 3001])
def test_invalid_message_text_does_not_create_confirmation(text):
    bot = TopBot()
    message = make_callback().message
    message.text = text

    top_actions.receive_top_message(clan_admin_context(message, bot))

    assert not bot.states
    assert not bot.data
    assert "Введите непустой текст" in bot.sent[-1][1]


def test_old_confirmation_does_not_send_or_discard_new_draft(monkeypatch):
    install_users(monkeypatch, [UserData(user_id=1, account_id=1, skill_summon_cost=25)])
    install_access(monkeypatch, True)
    bot = TopBot()
    invoke_callback(bot, "war_top_message/-100123/skills")
    bot.data["top_draft"] = ("a" * 12, "Новый текст", "admin")

    invoke_callback(bot, "war_top_send/" + "b" * 12)

    assert not bot.sent
    assert bot.data["top_draft"][1] == "Новый текст"
    assert "устарело" in bot.answers[-1][0][1]


def test_copy_with_no_tags_reports_empty_list(monkeypatch):
    install_users(monkeypatch, [UserData(user_id=1, extra_egg_chance=50)])
    install_access(monkeypatch, True)
    bot = TopBot()

    invoke_callback(bot, "war_top_copy/-100123/pets")

    assert not bot.sent
    assert "нет заполненных тегов" in bot.answers[-1][0][1]
