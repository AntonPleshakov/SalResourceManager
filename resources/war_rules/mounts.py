from decimal import Decimal
from resources.user_data import UserData
from resources.war_rules.details import ActivityDetails, format_calculation_number
from resources.war_rules.mount_packages import summon_packages as _summon_packages


MOUNT_CREATION_POINTS = 1_080
MOUNT_MERGE_POINTS = 1_080
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
        consumable_points=points,
        repeatable_points=Decimal("0"),
        inputs=(
            f"Ключи маунтов: {format_calculation_number(user.mount_keys.value)}",
            f"Снижение стоимости призыва: {user.mount_summon_cost.value}%",
            f"Шанс дополнительного маунта: {user.extra_mount_chance.value}%",
            f"Необъединённые маунты: "
            f"{format_calculation_number(user.unmerged_mounts.value)}",
        ),
        calculations=tuple(calculations),
    )


def calculate_mount_points(user: UserData) -> Decimal:
    return explain_mount_points(user).points
