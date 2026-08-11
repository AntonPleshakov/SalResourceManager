from telebot import TeleBot

from db.access_group import get_access_group_db
from db.user_data import get_user_data_db
from logger.app_logger import logger
from resources.egg_levels import EGG_LEVELS, EggLevel
from resources.user_data import (
    EDITABLE_FIELDS,
    PET_SETTINGS_FIELDS,
    RESOURCE_FIELDS,
    THOUSAND_INPUT_FIELDS,
    TRACKED_FIELDS,
    TECHNOLOGY_FIELDS,
    ResourceField,
    parse_editable_field_value,
)
from tg.user_data import accounts, editing, pets, resources, technologies
from tg.user_data.accounts import GameAccountStates, accounts_menu
from tg.user_data.common import (
    _get_group_tag,
    section_menu as _section_menu,
    value_input_hint as _value_input_hint,
)
from tg.user_data.editing import (
    EditUserDataStates,
    SECTION_FIELDS,
    SECTION_TITLES,
    _fill_prompt,
    _start_fill,
    fill_section,
    fill_tracked_fields,
    request_value,
    save_all_values,
    save_value,
)
from tg.user_data.pets import (
    change_hatch_batch_count,
    hatch_batches_menu,
    max_egg_level_menu,
    pets_menu,
    save_max_egg_level,
)
from tg.user_data.resources import resources_menu
from tg.user_data.technologies import technologies_menu


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering user data handlers")
    accounts.register_handlers(bot)
    resources.register_handlers(bot)
    technologies.register_handlers(bot)
    pets.register_handlers(bot)
    editing.register_handlers(bot)


__all__ = [
    "EDITABLE_FIELDS",
    "EGG_LEVELS",
    "EggLevel",
    "EditUserDataStates",
    "GameAccountStates",
    "PET_SETTINGS_FIELDS",
    "RESOURCE_FIELDS",
    "ResourceField",
    "SECTION_FIELDS",
    "SECTION_TITLES",
    "THOUSAND_INPUT_FIELDS",
    "TECHNOLOGY_FIELDS",
    "TRACKED_FIELDS",
    "_fill_prompt",
    "_get_group_tag",
    "_section_menu",
    "_start_fill",
    "_value_input_hint",
    "change_hatch_batch_count",
    "accounts_menu",
    "fill_section",
    "fill_tracked_fields",
    "get_access_group_db",
    "get_user_data_db",
    "hatch_batches_menu",
    "max_egg_level_menu",
    "parse_editable_field_value",
    "pets_menu",
    "register_handlers",
    "request_value",
    "resources_menu",
    "save_all_values",
    "save_max_egg_level",
    "save_value",
    "technologies_menu",
]
