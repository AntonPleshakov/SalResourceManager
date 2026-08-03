from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple


@dataclass(frozen=True)
class ActivityDetails:
    consumable_points: Decimal
    repeatable_points: Decimal
    inputs: Tuple[str, ...]
    calculations: Tuple[str, ...]

    @property
    def points(self) -> Decimal:
        return self.consumable_points + self.repeatable_points


def format_calculation_number(value: Decimal | int) -> str:
    decimal_value = Decimal(value).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    if decimal_value == decimal_value.to_integral():
        return f"{int(decimal_value):,}".replace(",", " ")
    return format(decimal_value.normalize(), "f")
