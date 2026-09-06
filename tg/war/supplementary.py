from decimal import Decimal
from html import escape

from tg.utils import format_points


def _format_resource_amount(amount: int) -> str:
    if amount >= 1_000:
        return format_points(Decimal(amount))
    return str(amount)


def flasks_summary(label: str, amount: int) -> str:
    return (
        '<table compact><caption>Дополнительные ресурсы</caption>'
        f"<tr><td>{escape(label)}</td>"
        f'<td align="right"><b>{_format_resource_amount(amount)}</b></td></tr>'
        "</table>"
    )
