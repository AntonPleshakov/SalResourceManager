from html import escape
from typing import Iterable

from telebot import TeleBot
from telebot.types import CallbackQuery, InputRichMessage, Message


_BUTTON_STYLES = frozenset({"danger", "success", "primary", "link"})
_HEADING_LEVELS = frozenset(range(1, 7))


def callback_button(text: str, data: str, style: str | None = None) -> str:
    if not 1 <= len(data.encode("utf-8")) <= 64:
        raise ValueError("Rich message callback data must contain 1-64 bytes")
    if style is not None and style not in _BUTTON_STYLES:
        raise ValueError(f"Unsupported rich message button style: {style}")

    style_attribute = f' style="{style}"' if style else ""
    return (
        f'<tg-button type="callback_data"{style_attribute} '
        f'data="{escape(data, quote=True)}">{escape(text)}</tg-button>'
    )


def button_row(
    buttons: Iterable[str], align: str | None = None
) -> str:
    if align is not None and align not in {"left", "center", "right"}:
        raise ValueError(f"Unsupported rich message button alignment: {align}")

    rendered_buttons = "".join(buttons)
    align_attribute = f' align="{align}"' if align else ""
    return f"<tg-button-row{align_attribute}>{rendered_buttons}</tg-button-row>"


def heading(text: str, level: int = 2) -> str:
    if level not in _HEADING_LEVELS:
        raise ValueError("Rich message heading level must be between 1 and 6")
    return f"<h{level}>{escape(text)}</h{level}>"


def footer(text: str) -> str:
    return f"<footer>{escape(text)}</footer>"


def notice(html: str) -> str:
    return f"<blockquote>{html}</blockquote>"


def details(summary: str, html: str, *, opened: bool = False) -> str:
    open_attribute = " open" if opened else ""
    return (
        f"<details{open_attribute}><summary>{escape(summary)}</summary>"
        f"{html}</details>"
    )


def back_button(text: str, data: str) -> str:
    return button_row(
        (callback_button(text, data),),
        align="left",
    )


def confirmation_buttons(
    confirm_text: str,
    confirm_data: str,
    cancel_text: str,
    cancel_data: str,
    *,
    destructive: bool = False,
) -> str:
    return "".join(
        (
            button_row(
                (
                    callback_button(
                        confirm_text,
                        confirm_data,
                        style="danger" if destructive else "primary",
                    ),
                )
            ),
            back_button(cancel_text, cancel_data),
        )
    )


def account_context(tag: str, clan_title: str = "") -> str:
    display_tag = tag.strip() or "не указан"
    clan = f" · Клан: <b>{escape(clan_title)}</b>" if clan_title else ""
    return f"<footer>Аккаунт: <b>{escape(display_tag)}</b>{clan}</footer>"


def highlight_metric(label: str, value: str) -> str:
    return f"<aside>{escape(label)}<br><b>{escape(value)}</b></aside>"


def input_rich_message(parts: Iterable[str]) -> InputRichMessage:
    return InputRichMessage(
        html="".join(parts),
        skip_entity_detection=True,
    )


def edit_rich_message(
    bot: TeleBot,
    chat_id: int,
    message_id: int,
    rich_message: InputRichMessage,
) -> None:
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        rich_message=rich_message,
    )


def deliver_rich_message(
    update: Message | CallbackQuery,
    bot: TeleBot,
    rich_message: InputRichMessage,
) -> None:
    if isinstance(update, CallbackQuery):
        edit_rich_message(
            bot,
            update.message.chat.id,
            update.message.id,
            rich_message,
        )
        return

    bot.send_rich_message(update.chat.id, rich_message)
