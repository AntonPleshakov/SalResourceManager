from html import escape
from typing import Iterable

from telebot.types import InputRichMessage


_BUTTON_STYLES = frozenset({"danger", "success", "primary", "link"})


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


def input_rich_message(parts: Iterable[str]) -> InputRichMessage:
    return InputRichMessage(
        html="".join(parts),
        skip_entity_detection=True,
    )
