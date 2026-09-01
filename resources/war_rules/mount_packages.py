from typing import Tuple

from resources.war_rules.details import format_calculation_number


MOUNT_SUMMON_PACKAGES: Tuple[Tuple[int, int], ...] = (
    (50, 2_500),
    (15, 750),
    (1, 50),
)


def discounted_cost(base_cost: int, discount: int) -> int:
    return (base_cost * (100 - discount) + 99) // 100


def summon_packages(
    keys: int, discount: int
) -> tuple[int, int, Tuple[str, ...]]:
    summoned_mounts = 0
    remaining_keys = keys
    calculations = []
    for mount_count, base_cost in MOUNT_SUMMON_PACKAGES:
        cost = discounted_cost(base_cost, discount)
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
