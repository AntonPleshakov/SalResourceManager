from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Any, Mapping, TypeVar

from telebot import TeleBot, formatting
from telebot.handler_backends import State, StatesGroup

import resources.user_data as user_data_resources
from tg.utils import empty_filter, format_points


class EditUserDataStates(StatesGroup):
    value = State()
    fill_values = State()


PRIVATE_CALLBACK_HANDLER = {
    "func": empty_filter,
    "is_private": True,
    "pass_bot": True,
}
PRIVATE_TEXT_HANDLER = {
    "content_types": ["text"],
    "chat_types": ["private"],
    "pass_bot": True,
}


@dataclass(frozen=True)
class FillSection:
    title: str
    fields: tuple[user_data_resources.ResourceField, ...] | None
    finish_callback: str
    finish_button: str


FILL_SECTIONS = {
    "resources": FillSection(
        title="ресурсы",
        fields=user_data_resources.RESOURCE_FIELDS,
        finish_callback="resources",
        finish_button="Вернуться к ресурсам",
    ),
    "technologies": FillSection(
        title="технологии",
        fields=user_data_resources.TECHNOLOGY_FIELDS,
        finish_callback="technologies",
        finish_button="Вернуться к технологиям",
    ),
    "reminder": FillSection(
        title="данные из напоминания",
        fields=None,
        finish_callback="home",
        finish_button="Назад в меню",
    ),
}

VALUE_EDIT_SECTIONS = {
    **{field.name: "resources" for field in user_data_resources.RESOURCE_FIELDS},
    **{
        field.name: "technologies"
        for field in user_data_resources.TECHNOLOGY_FIELDS
    },
    "eggs_per_hatch_batch": "pets",
}


@dataclass(frozen=True)
class ValueEditState:
    field_name: str
    account_id: int

    @property
    def field(self) -> user_data_resources.ResourceField:
        return user_data_resources.EDITABLE_FIELDS[self.field_name]

    @property
    def section(self) -> str:
        return VALUE_EDIT_SECTIONS[self.field_name]

    def is_valid(self) -> bool:
        return self.field_name in VALUE_EDIT_SECTIONS and isinstance(
            self.account_id, int
        )


@dataclass(frozen=True)
class FillState:
    section: str
    field_names: tuple[str, ...]
    index: int
    account_id: int
    account_tag: str
    prompt_message_id: int

    @classmethod
    def start(
        cls,
        section: str,
        fields: tuple[user_data_resources.ResourceField, ...],
        current_user: user_data_resources.UserData,
        prompt_message_id: int,
    ) -> "FillState":
        return cls(
            section=section,
            field_names=tuple(field.name for field in fields),
            index=0,
            account_id=current_user.account_id.value,
            account_tag=current_user.tag.value,
            prompt_message_id=prompt_message_id,
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_names", tuple(self.field_names))

    @property
    def config(self) -> FillSection:
        return FILL_SECTIONS[self.section]

    @property
    def fields(self) -> tuple[user_data_resources.ResourceField, ...]:
        return tuple(
            user_data_resources.EDITABLE_FIELDS[name]
            for name in self.field_names
        )

    @property
    def current_field(self) -> user_data_resources.ResourceField:
        return self.fields[self.index]

    @property
    def is_last_step(self) -> bool:
        return self.index + 1 >= len(self.field_names)

    def next_step(self) -> "FillState":
        return replace(self, index=self.index + 1)

    def is_valid(self) -> bool:
        if (
            self.section not in FILL_SECTIONS
            or not self.field_names
            or len(self.field_names) != len(set(self.field_names))
            or not all(
                name in user_data_resources.EDITABLE_FIELDS
                for name in self.field_names
            )
            or not isinstance(self.index, int)
            or not 0 <= self.index < len(self.field_names)
            or not isinstance(self.account_id, int)
            or not isinstance(self.account_tag, str)
            or not isinstance(self.prompt_message_id, int)
        ):
            return False

        configured_fields = self.config.fields
        if configured_fields is not None:
            return self.field_names == tuple(
                field.name for field in configured_fields
            )
        tracked_names = {
            field.name for field in user_data_resources.TRACKED_FIELDS
        }
        return all(name in tracked_names for name in self.field_names)


StateType = TypeVar("StateType", ValueEditState, FillState)


def load_state(
    bot: TeleBot,
    user_id: int,
    key: str,
    state_type: type[StateType],
) -> StateType | None:
    with bot.retrieve_data(user_id) as data:
        payload = data.get(key)
    if not isinstance(payload, Mapping):
        return None
    try:
        state = state_type(**dict(payload))
    except (KeyError, TypeError, ValueError):
        return None
    return state if state.is_valid() else None


def save_state(bot: TeleBot, user_id: int, key: str, state: Any) -> None:
    bot.add_data(user_id, **{key: asdict(state)})


def account_line(account_tag: str) -> str:
    return (
        "Игровой аккаунт: "
        f"<b>{formatting.escape_html(account_tag)}</b>\n\n"
    )


def format_field_value(
    field: user_data_resources.ResourceField, value: int | str
) -> str:
    displayed_value = str(value)
    if (
        field in user_data_resources.RESOURCE_FIELDS
        and Decimal(displayed_value) >= Decimal("1000")
    ):
        return format_points(Decimal(displayed_value))
    return displayed_value
