from telebot import TeleBot

from tg.utils import empty_filter


def register_handlers(bot: TeleBot) -> None:
    from tg.user_data.accounts import (
        GameAccountStates,
        accounts_menu,
        confirm_delete,
        create_initial_account,
        delete_account,
        request_add,
        request_add_nickname,
        request_delete,
        request_rename,
        save_nickname,
        select_account,
    )

    callback_defaults = {
        "func": empty_filter,
        "is_private": True,
        "pass_bot": True,
    }
    callback_handlers = (
        (
            accounts_menu,
            r"accounts(?:/(resources|technologies|pets|war_calculator))?",
        ),
        (
            request_add,
            r"accounts/add(?:/(accounts|resources|technologies|pets|war_calculator))?",
        ),
        (request_rename, "accounts/rename"),
        (
            request_add_nickname,
            r"accounts/add/(accounts|resources|technologies|pets|war_calculator)/clan/-?[0-9]+",
        ),
        (create_initial_account, r"accounts/create/-?[0-9]+"),
        (
            select_account,
            r"accounts/select/(accounts|resources|technologies|pets|war_calculator)/[0-9]+",
        ),
        (request_delete, "accounts/delete"),
        (confirm_delete, r"accounts/delete/confirm/[0-9]+"),
        (delete_account, r"accounts/delete/[0-9]+"),
    )
    for handler, button in callback_handlers:
        bot.register_callback_query_handler(
            handler,
            button=button,
            **callback_defaults,
        )
    bot.register_message_handler(
        save_nickname,
        content_types=["text"],
        chat_types=["private"],
        state=GameAccountStates.nickname,
        pass_bot=True,
    )
