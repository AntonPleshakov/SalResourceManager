from telebot import TeleBot

from tg.handlers import HandlerRegistry


def register_handlers(bot: TeleBot) -> None:
    from tg.user_data.accounts import (
        GameAccountStates,
        accounts_menu,
        confirm_delete,
        create_initial_account,
        delete_account,
        leave_clan,
        move_account,
        request_add,
        request_add_nickname,
        request_delete,
        request_move,
        request_rename,
        save_nickname,
        select_account,
    )

    handlers = HandlerRegistry(bot)
    callback_handlers = (
        (
            accounts_menu,
            r"accounts(?:/(resources|technologies|pets|war_calculator))?",
        ),
        (
            request_add,
            r"accounts/add(?:/(accounts|resources|technologies|pets|war_calculator))?",
        ),
        (
            request_rename,
            r"accounts/rename(?:/(accounts|resources|technologies|pets|war_calculator))?",
        ),
        (
            request_move,
            r"accounts/move(?:/(accounts|resources|technologies|pets|war_calculator))?",
        ),
        (
            request_add_nickname,
            r"accounts/add/(accounts|resources|technologies|pets|war_calculator)/clan/-?[0-9]+",
        ),
        (create_initial_account, r"accounts/create/-?[0-9]+"),
        (
            move_account,
            r"accounts/move/[0-9]+/clan/-?[0-9]+"
            r"(?:/(resources|technologies|pets|war_calculator))?",
        ),
        (
            leave_clan,
            r"accounts/move/[0-9]+/leave(?:/confirm)?"
            r"/(accounts|resources|technologies|pets|war_calculator)",
        ),
        (
            select_account,
            r"accounts/select/(accounts|resources|technologies|pets|war_calculator)/[0-9]+",
        ),
        (
            request_delete,
            r"accounts/delete/menu/(accounts|resources|technologies|pets|war_calculator)",
        ),
        (
            confirm_delete,
            r"accounts/delete/confirm/[0-9]+/(accounts|resources|technologies|pets|war_calculator)",
        ),
        (
            delete_account,
            r"accounts/delete/[0-9]+/(accounts|resources|technologies|pets|war_calculator)",
        ),
    )
    for handler, button in callback_handlers:
        handlers.private_callback(
            handler,
            button=button,
        )
    handlers.private_message(
        save_nickname,
        content_types=["text"],
        state=GameAccountStates.nickname,
    )
