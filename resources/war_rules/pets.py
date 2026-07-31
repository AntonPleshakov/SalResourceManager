from decimal import Decimal
from resources.user_data import UserData


PET_OR_EGG_MERGE_POINTS = 2_250
SHELLS_PER_EGG = 100
EGGS_PER_HATCH_BATCH = 4
SIXTH_LEVEL_EGG_POINTS = 46_080
FIFTH_LEVEL_EGG_POINTS = 23_040
MAX_HATCHING_POINTS_IN_ADVANCE = (
    SIXTH_LEVEL_EGG_POINTS * Decimal(EGGS_PER_HATCH_BATCH)
)
MAX_HATCHING_POINTS_PER_DAY = (
    Decimal(SIXTH_LEVEL_EGG_POINTS) * Decimal(EGGS_PER_HATCH_BATCH)
    + Decimal(FIFTH_LEVEL_EGG_POINTS) * Decimal(EGGS_PER_HATCH_BATCH)
)


def calculate_pet_points(user: UserData) -> Decimal:
    eggs = _purchased_egg_count(user)
    merge_points = (Decimal(user.pets.value) + eggs) * PET_OR_EGG_MERGE_POINTS
    return merge_points + MAX_HATCHING_POINTS_PER_DAY + MAX_HATCHING_POINTS_IN_ADVANCE


def _purchased_egg_count(user: UserData) -> Decimal:
    base_eggs = Decimal(user.shells.value) / SHELLS_PER_EGG
    return base_eggs * (
        Decimal("1") + Decimal(user.extra_egg_chance.value) / Decimal("100")
    )
