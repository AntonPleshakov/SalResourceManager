from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number


MOUNT_CREATION_POINTS = 1_080
MOUNT_MERGE_POINTS = 1_080
MOUNT_SUMMON_PACKAGES: Tuple[Tuple[int, int], ...] = (
    (50, 2_500),
    (15, 750),
    (1, 50),
)


def calculate_mount_points(user: UserData) -> Decimal:
    return explain_mount_points(user).points


def explain_mount_points(user: UserData) -> ActivityDetails:
    base_mounts, remaining_keys, package_calculations = _summon_packages(
        user.mount_keys.value,
        user.mount_summon_cost.value,
    )
    bonus_multiplier = (
        Decimal("1")
        + Decimal(user.extra_mount_chance.value) / Decimal("100")
    )
    summoned_mounts = Decimal(base_mounts) * bonus_multiplier
    created_points = summoned_mounts * MOUNT_CREATION_POINTS
    merged_points = (summoned_mounts + user.unmerged_mounts.value) * MOUNT_MERGE_POINTS
    points = created_points + merged_points
    calculations = [*package_calculations]
    if not package_calculations:
        calculations.append("На доступные ключи нельзя купить пакет призыва")
    calculations.extend(
        [
            f"После покупки пакетов осталось ключей: "
            f"{format_calculation_number(remaining_keys)}",
            f"Призвано с учётом доп. шанса: "
            f"{format_calculation_number(base_mounts)} × "
            f"{format_calculation_number(bonus_multiplier)} = "
            f"{format_calculation_number(summoned_mounts)}",
            f"Создание: {format_calculation_number(summoned_mounts)} × "
            f"{format_calculation_number(MOUNT_CREATION_POINTS)} = "
            f"{format_calculation_number(created_points)} очков",
            f"Объединение: ({format_calculation_number(summoned_mounts)} + "
            f"{format_calculation_number(user.unmerged_mounts.value)}) × "
            f"{format_calculation_number(MOUNT_MERGE_POINTS)} = "
            f"{format_calculation_number(merged_points)} очков",
            f"Итого: {format_calculation_number(created_points)} + "
            f"{format_calculation_number(merged_points)} = "
            f"{format_calculation_number(points)} очков",
        ]
    )
    return ActivityDetails(
        points=points,
        inputs=(
            f"Ключи маунтов: {format_calculation_number(user.mount_keys.value)}",
            f"Снижение стоимости призыва: {user.mount_summon_cost.value}%",
            f"Шанс дополнительного маунта: {user.extra_mount_chance.value}%",
            f"Необъединённые маунты: "
            f"{format_calculation_number(user.unmerged_mounts.value)}",
        ),
        calculations=tuple(calculations),
    )


def _summon_packages(
    keys: int, discount: int
) -> tuple[int, int, Tuple[str, ...]]:
    summoned_mounts = 0
    remaining_keys = keys
    calculations = []
    for mount_count, base_cost in MOUNT_SUMMON_PACKAGES:
        cost = _discounted_cost(base_cost, discount)
        package_count, remaining_keys = divmod(remaining_keys, cost)
        summoned_mounts += package_count * mount_count
        if package_count:
            calculations.append(
                f"Пакеты по {mount_count}: цена "
                f"{format_calculation_number(base_cost)} со скидкой {discount}% → "
                f"{format_calculation_number(cost)} ключей; "
                f"{package_count} пак. → "
                f"{format_calculation_number(package_count * mount_count)} маунтов"
            )
    return summoned_mounts, remaining_keys, tuple(calculations)


def _summoned_mount_count(
    keys: int, discount: int, extra_mount_chance: int
) -> Decimal:
    summoned_mounts, _, _ = _summon_packages(keys, discount)
    return Decimal(summoned_mounts) * (
        Decimal("1") + Decimal(extra_mount_chance) / Decimal("100")
    )


def _discounted_cost(base_cost: int, discount: int) -> int:
    return (base_cost * (100 - discount) + 99) // 100
