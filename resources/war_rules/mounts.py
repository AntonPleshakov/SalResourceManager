from decimal import Decimal
from typing import Tuple

from resources.user_data import UserData


MOUNT_CREATION_POINTS = 1_080
MOUNT_MERGE_POINTS = 1_080
MOUNT_SUMMON_PACKAGES: Tuple[Tuple[int, int], ...] = (
    (50, 2_500),
    (15, 750),
    (1, 50),
)


def calculate_mount_points(user: UserData) -> Decimal:
    summoned_mounts = _summoned_mount_count(
        user.mount_keys.value, user.mount_summon_cost.value, user.extra_mount_chance.value
    )
    created_points = summoned_mounts * MOUNT_CREATION_POINTS
    merged_points = (summoned_mounts + user.unmerged_mounts.value) * MOUNT_MERGE_POINTS
    return created_points + merged_points


def _summoned_mount_count(
    keys: int, discount: int, extra_mount_chance: int
) -> Decimal:
    summoned_mounts = 0
    remaining_keys = keys
    for mount_count, base_cost in MOUNT_SUMMON_PACKAGES:
        cost = _discounted_cost(base_cost, discount)
        package_count, remaining_keys = divmod(remaining_keys, cost)
        summoned_mounts += package_count * mount_count
    return Decimal(summoned_mounts) * (
        Decimal("1") + Decimal(extra_mount_chance) / Decimal("100")
    )


def _discounted_cost(base_cost: int, discount: int) -> int:
    return (base_cost * (100 - discount) + 99) // 100
