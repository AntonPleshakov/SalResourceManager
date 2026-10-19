import pytest

from db.database import Database
from db.user_data import UserDataDB
from resources.technology_language import field_title
from resources.user_data import EDITABLE_FIELDS, UserData
from tg.user_data.technologies import build_technologies_menu


@pytest.mark.parametrize("language, expected", [
    ("en", "Chance to summon an extra egg"),
    ("de", "Chance, ein zusätzliches ei zu beschwören"),
    ("ru", "Доп. шанс на яйцо"),
])
def test_technology_menu_language(language, expected):
    html = build_technologies_menu(UserData(), language=language).rich_message.html
    assert expected in html
    assert "Изменить" in html
    assert field_title(EDITABLE_FIELDS["hammers"], language) == "Молотки"


def test_language_preference_survives_database_reopen(tmp_path):
    path = tmp_path / "language.db"
    database = UserDataDB(Database(path))
    database.update_username(42, "tester")
    assert database.get_game_language(42) == "ru"
    database.set_game_language(42, "de")
    reopened = UserDataDB(Database(path))
    assert reopened.get_game_language(42) == "de"
    with pytest.raises(ValueError):
        reopened.set_game_language(42, "fr")
    assert reopened.get_game_language(42) == "de"
