"""Safe, explicit registration profiles for Telegram handlers."""

from dataclasses import dataclass
from functools import wraps
from inspect import Parameter, signature
from typing import Any, Callable, Protocol, Sequence, Union

from telebot import TeleBot
from telebot.types import CallbackQuery, Message, ReplyKeyboardRemove

from db.access_group import AccessGroup
from logger.app_logger import logger
from tg.utils import empty_filter, get_ids, get_username


Update = Union[Message, CallbackQuery]
Handler = Callable[..., Any]
_UNSET = object()


@dataclass(frozen=True)
class HandlerContext:
    update: Update
    bot: TeleBot
    user_id: int
    chat_id: int
    message_id: int
    username: str


@dataclass(frozen=True)
class AdminContext(HandlerContext):
    clans: tuple[AccessGroup, ...]


@dataclass(frozen=True)
class ClanAdminContext(HandlerContext):
    group: AccessGroup


class HandlerPolicy(Protocol):
    def authorize(self, context: HandlerContext) -> HandlerContext:
        """Return a richer context or raise when access must be denied."""


@dataclass(frozen=True)
class CurrentAdmin(HandlerPolicy):
    def authorize(self, context: HandlerContext) -> AdminContext:
        from tg.admins.common import get_current_admin_clans

        clans = tuple(get_current_admin_clans(context.bot, context.user_id))
        if not clans:
            raise ValueError("Нет актуальных прав администратора клана")
        return AdminContext(**context.__dict__, clans=clans)


@dataclass(frozen=True)
class ActiveClan(HandlerPolicy):
    def authorize(self, context: HandlerContext) -> ClanAdminContext:
        from tg.admins.common import get_active_admin_group

        group = get_active_admin_group(context.bot, context.user_id)
        return ClanAdminContext(**context.__dict__, group=group)


@dataclass(frozen=True)
class ClanFromState(HandlerPolicy):
    key: str = "admin_group_id"

    def authorize(self, context: HandlerContext) -> ClanAdminContext:
        with context.bot.retrieve_data(context.user_id) as data:
            group_id = data.get(self.key)
        if not isinstance(group_id, int):
            raise ValueError("Не выбран клан")
        return _authorize_clan(context, group_id)


@dataclass(frozen=True)
class ClanFromCallback(HandlerPolicy):
    segment: int = -1

    def authorize(self, context: HandlerContext) -> ClanAdminContext:
        if not isinstance(context.update, CallbackQuery):
            raise ValueError("Не удалось определить выбранный клан")
        try:
            group_id = int(context.update.data.split("/")[self.segment])
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError("Не удалось определить выбранный клан") from error
        return _authorize_clan(context, group_id)


def _authorize_clan(
    context: HandlerContext, group_id: int
) -> ClanAdminContext:
    from db.initializer import get_admins_db
    from tg.admins.common import require_admin_access

    admins = get_admins_db()
    require_admin_access(context.bot, context.user_id, group_id, admins)
    group = next(
        (
            candidate
            for candidate in admins.get_clans(context.user_id)
            if candidate.group_id == group_id
        ),
        None,
    )
    if group is None:
        raise ValueError("Клан не найден")
    return ClanAdminContext(**context.__dict__, group=group)


def _build_context(update: Update, bot: TeleBot) -> HandlerContext:
    user_id, chat_id, message_id = get_ids(update)
    return HandlerContext(
        update=update,
        bot=bot,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        username=get_username(update),
    )


def _invoke_handler(
    handler: Handler,
    context: HandlerContext,
) -> Any:
    return handler(context)


def _validate_policy_handler(handler: Handler) -> None:
    parameters = list(signature(handler).parameters.values())
    if (
        len(parameters) != 1
        or parameters[0].name != "context"
        or parameters[0].kind
        not in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
    ):
        raise TypeError(
            "Protected handler must accept exactly one 'context' argument: "
            f"{handler.__module__}.{handler.__name__}"
        )


def _deny_policy_access(
    update: Update,
    bot: TeleBot,
    error: Exception,
    *,
    clear_state: bool,
) -> None:
    user_id, chat_id = get_ids(update)[:2]
    if clear_state:
        bot.delete_state(user_id)
    text = str(error) or "Недостаточно прав для выполнения действия"
    logger.warning(
        "Telegram handler policy denied access user_id=%s username=%s "
        "reason=%s",
        user_id,
        get_username(update),
        type(error).__name__,
    )
    if isinstance(update, CallbackQuery):
        bot.answer_callback_query(update.id, text, show_alert=True)
        return
    bot.send_message(
        chat_id,
        text,
        reply_markup=ReplyKeyboardRemove() if clear_state else None,
    )


def _with_policy(
    handler: Handler,
    policy: HandlerPolicy,
    *,
    clear_state_on_denial: bool,
) -> Handler:
    _validate_policy_handler(handler)

    @wraps(handler)
    def secured(update: Update, bot: TeleBot) -> Any:
        try:
            context = policy.authorize(_build_context(update, bot))
        except (RuntimeError, ValueError) as error:
            _deny_policy_access(
                update,
                bot,
                error,
                clear_state=clear_state_on_denial,
            )
            return None
        return _invoke_handler(handler, context)

    setattr(secured, "_srm_handler_policy", policy)
    return secured


def _set_optional_filter(
    filters: dict[str, Any], key: str, value: Any
) -> None:
    if value is not _UNSET:
        filters[key] = value


class HandlerRegistry:
    """Register handlers through a small set of fail-closed profiles."""

    def __init__(self, bot: TeleBot):
        self._bot = bot

    def private_callback(
        self,
        handler: Handler,
        *,
        button: str | None = None,
        state: Any = _UNSET,
        admin: bool | None = None,
    ) -> None:
        filters: dict[str, Any] = {
            "func": empty_filter,
            "is_private": True,
            "pass_bot": True,
        }
        if button is not None:
            filters["button"] = button
        _set_optional_filter(filters, "state", state)
        if admin is not None:
            filters["is_admin"] = admin
        self._bot.register_callback_query_handler(handler, **filters)

    def admin_callback(
        self,
        handler: Handler,
        *,
        button: str,
        state: Any = _UNSET,
    ) -> None:
        self._policy_callback(
            handler,
            button=button,
            policy=CurrentAdmin(),
            state=state,
        )

    def clan_admin_callback(
        self,
        handler: Handler,
        *,
        button: str,
        clan: HandlerPolicy,
        state: Any = _UNSET,
    ) -> None:
        self._policy_callback(
            handler,
            button=button,
            policy=clan,
            state=state,
        )

    def _policy_callback(
        self,
        handler: Handler,
        *,
        button: str,
        policy: HandlerPolicy,
        state: Any,
    ) -> None:
        secured = _with_policy(
            handler,
            policy,
            clear_state_on_denial=state is not _UNSET,
        )
        self.private_callback(
            secured,
            button=button,
            state=state,
            admin=True,
        )

    def private_message(
        self,
        handler: Handler,
        *,
        content_types: Sequence[str] | None = None,
        commands: Sequence[str] | None = None,
        state: Any = _UNSET,
        predicate: Callable[[Message], bool] | None = None,
        admin: bool | None = None,
    ) -> None:
        filters: dict[str, Any] = {
            "chat_types": ["private"],
            "pass_bot": True,
        }
        if content_types is not None:
            filters["content_types"] = list(content_types)
        if commands is not None:
            filters["commands"] = list(commands)
        if predicate is not None:
            filters["func"] = predicate
        _set_optional_filter(filters, "state", state)
        if admin is not None:
            filters["is_admin"] = admin
        self._bot.register_message_handler(handler, **filters)

    def admin_message(
        self,
        handler: Handler,
        *,
        content_types: Sequence[str],
        state: Any,
        predicate: Callable[[Message], bool] | None = None,
    ) -> None:
        self._policy_message(
            handler,
            content_types=content_types,
            state=state,
            policy=CurrentAdmin(),
            predicate=predicate,
        )

    def clan_admin_message(
        self,
        handler: Handler,
        *,
        content_types: Sequence[str],
        state: Any,
        clan: HandlerPolicy,
        predicate: Callable[[Message], bool] | None = None,
    ) -> None:
        self._policy_message(
            handler,
            content_types=content_types,
            state=state,
            policy=clan,
            predicate=predicate,
        )

    def _policy_message(
        self,
        handler: Handler,
        *,
        content_types: Sequence[str],
        state: Any,
        policy: HandlerPolicy,
        predicate: Callable[[Message], bool] | None,
    ) -> None:
        secured = _with_policy(
            handler,
            policy,
            clear_state_on_denial=True,
        )
        self.private_message(
            secured,
            content_types=content_types,
            state=state,
            predicate=predicate,
            admin=True,
        )

    def group_message(
        self,
        handler: Handler,
        *,
        chat_types: Sequence[str],
        commands: Sequence[str] | None = None,
        content_types: Sequence[str] | None = None,
    ) -> None:
        filters: dict[str, Any] = {
            "chat_types": list(chat_types),
            "pass_bot": True,
        }
        if commands is not None:
            filters["commands"] = list(commands)
        if content_types is not None:
            filters["content_types"] = list(content_types)
        self._bot.register_message_handler(handler, **filters)
