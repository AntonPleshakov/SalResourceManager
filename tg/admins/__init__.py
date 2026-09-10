from collections.abc import Sequence

from telebot import TeleBot
from telebot.types import CallbackQuery

from db.access_group import AccessGroup
from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.admins import (
    add_admin,
    clan_technologies,
    clans,
    del_admin,
    game_data,
    notifications,
    rename_clan,
    resource_status,
)
from tg.handlers import (
    ActiveClan,
    AdminContext,
    ClanAdminContext,
    HandlerRegistry,
)
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    footer,
    heading,
    input_rich_message,
)
from tg.utils import get_ids, get_user_link, get_username


def _show_admins_main_menu(
    callback_query: CallbackQuery,
    bot: TeleBot,
    groups: Sequence[AccessGroup],
) -> None:
    user_id, chat_id, message_id = get_ids(callback_query)
    logger.debug(
        "Opening admin menu for user_id=%s username=%s",
        user_id,
        get_username(callback_query),
    )
    bot.delete_state(user_id)
    admins = get_admins_db()
    active_group = admins.get_active_group(user_id)
    group = next(
        (
            candidate
            for candidate in groups
            if active_group is not None
            and candidate.group_id == active_group.group_id
        ),
        None,
    )
    if group is None:
        parts = [heading("Админ-панель")]
        if groups:
            parts.extend(
                (
                    "<p>Выберите клан для административных "
                    "действий.</p>",
                    button_row(
                        (
                            callback_button(
                                "🏰 Выбрать клан",
                                "admins/clans",
                                style="primary",
                            ),
                        )
                    ),
                    button_row(
                        (
                            callback_button(
                                "➕ Добавить клан", "admins/register_group"
                            ),
                        )
                    ),
                )
            )
        else:
            parts.append(
                "<p>У вас нет актуальных прав администратора клана.</p>"
            )
        parts.append(back_button("⬅️ Главное меню", "home"))
        edit_rich_message(
            bot,
            chat_id,
            message_id,
            input_rich_message(parts),
        )
        return

    parts = [
        heading("Админ-панель"),
        footer(f"Клан: {group.title}"),
        heading("Игроки", level=3),
        button_row(
            (
                callback_button("👥 Обновления", "admins/last_updates"),
                callback_button("📊 Игровые данные", "admins/game_data"),
            )
        ),
        heading("Коммуникации", level=3),
        button_row(
            (
                callback_button(
                    "📣 Уведомления",
                    "admins/notifications",
                    style="primary",
                ),
            )
        ),
        heading("Настройки клана", level=3),
        button_row(
            (
                callback_button(
                    "🔬 Клановые технологии",
                    "admins/clan_technologies",
                    style="primary",
                ),
            )
        ),
        button_row(
            (
                callback_button("➕ Добавить клан", "admins/register_group"),
                callback_button("✏️ Переименовать", "admins/rename_clan"),
            )
        ),
    ]
    if len(groups) > 1:
        parts.append(
            button_row((callback_button("🔄 Сменить клан", "admins/clans"),))
        )
    parts.extend(
        (
            heading("Доступ", level=3),
            button_row(
                (
                    callback_button(
                        "👥 Администраторы", "admins/admins_list"
                    ),
                    callback_button("➕ Добавить", "admins/add_admins"),
                )
            ),
            button_row(
                (
                    callback_button(
                        "🗑 Отозвать права",
                        "admins/del_admin",
                        style="danger",
                    ),
                )
            ),
            back_button("⬅️ Главное меню", "home"),
        )
    )
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
    )


def admins_main_menu(context: AdminContext) -> None:
    _show_admins_main_menu(
        context.update,
        context.bot,
        list(context.clans),
    )


def admins_list(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    admins_db = get_admins_db()
    admins = admins_db.get_clan_admins(context.group.group_id)
    logger.debug(
        "Showing admin list to user_id=%s username=%s count=%d",
        callback_query.from_user.id,
        get_username(callback_query),
        len(admins),
    )
    items = "".join(
        f"<li>{get_user_link(admin.user_id.value, admin.username.value)}</li>"
        for admin in admins
    )
    chat_id, message_id = get_ids(callback_query)[1:]
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(
            (
                heading("Администраторы"),
                f"<ul>{items}</ul>",
                back_button("⬅️ Админ-панель", "admins"),
            )
        ),
    )


def register_handlers(bot: TeleBot):
    logger.debug("Registering admin handlers")
    handlers = HandlerRegistry(bot)
    handlers.admin_callback(
        admins_main_menu,
        button="admins",
    )
    handlers.clan_admin_callback(
        admins_list,
        button="admins/admins_list",
        clan=ActiveClan(),
    )
    add_admin.register_handlers(bot)
    clan_technologies.register_handlers(bot)
    clans.register_handlers(bot)
    del_admin.register_handlers(bot)
    game_data.register_handlers(bot)
    notifications.register_handlers(bot)
    rename_clan.register_handlers(bot)
    resource_status.register_handlers(bot)
    logger.info("Admin handlers registered")
