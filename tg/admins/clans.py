from telebot import TeleBot

from db.initializer import get_admins_db
from logger.app_logger import logger
from tg.admins.common import get_current_admin_clans
from tg.handlers import (
    AdminContext,
    ClanAdminContext,
    ClanFromCallback,
    HandlerRegistry,
)
from tg.rich import (
    back_button,
    button_row,
    callback_button,
    edit_rich_message,
    heading,
    input_rich_message,
)
from tg.utils import get_ids


def clans_menu(context: AdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id, chat_id, message_id = get_ids(callback_query)
    groups = list(context.clans)
    parts = [
        heading("Управляемый клан"),
        "<p>Выберите клан для административных действий.</p>",
    ]
    for group in groups:
        parts.append(
            button_row(
                (
                    callback_button(
                        f"🏰 {group.title}",
                        f"admins/clans/{group.group_id}",
                    ),
                )
            )
        )
    parts.append(back_button("⬅️ Админ-панель", "admins"))
    edit_rich_message(
        bot,
        chat_id,
        message_id,
        input_rich_message(parts),
    )


def select_clan(context: ClanAdminContext) -> None:
    callback_query = context.update
    bot = context.bot
    user_id = callback_query.from_user.id
    try:
        group_id = context.group.group_id
        admins = get_admins_db()
        admins.select_group(user_id, group_id)
    except ValueError as error:
        bot.answer_callback_query(callback_query.id, str(error), show_alert=True)
        return

    from tg.admins import _show_admins_main_menu

    groups = get_current_admin_clans(bot, user_id, admins)
    _show_admins_main_menu(callback_query, bot, groups)


def register_handlers(bot: TeleBot) -> None:
    logger.debug("Registering admin clan-selection handlers")
    handlers = HandlerRegistry(bot)
    handlers.admin_callback(
        clans_menu,
        button="admins/clans",
    )
    handlers.clan_admin_callback(
        select_clan,
        button=r"admins/clans/-?[0-9]+",
        clan=ClanFromCallback(),
    )
