import pytest

from resources.technology_badges import max_technology_badges
from resources.user_data import UserData


def test_max_technology_badges_are_empty_below_maximums():
    user = UserData(
        skill_summon_cost=24,
        mount_summon_cost=24,
        extra_mount_chance=49,
        extra_egg_chance=49,
    )

    assert max_technology_badges(user) == ""


def test_max_technology_badges_replace_all_completed_groups_with_one_badge():
    user = UserData(
        skill_summon_cost=25,
        mount_summon_cost=25,
        extra_mount_chance=50,
        extra_egg_chance=50,
    )

    assert max_technology_badges(user) == "🏆"


@pytest.mark.parametrize(
    "skills, mounts, pets, expected",
    [
        (True, False, False, "🎟️"),
        (False, True, False, "🐎"),
        (False, False, True, "🥚"),
        (True, True, False, "🎟️🐎"),
        (True, False, True, "🎟️🥚"),
        (False, True, True, "🐎🥚"),
    ],
)
def test_incomplete_groups_keep_individual_badges(skills, mounts, pets, expected):
    user = UserData(
        skill_summon_cost=25 if skills else 24,
        mount_summon_cost=25 if mounts else 24,
        extra_mount_chance=50 if mounts else 49,
        extra_egg_chance=50 if pets else 49,
    )

    assert max_technology_badges(user) == expected


def test_mount_badge_requires_both_mount_technologies():
    missing_cost = UserData(
        skill_summon_cost=25,
        extra_egg_chance=50,
        mount_summon_cost=24,
        extra_mount_chance=50,
    )
    missing_chance = UserData(
        skill_summon_cost=25,
        extra_egg_chance=50,
        mount_summon_cost=25,
        extra_mount_chance=49,
    )

    assert max_technology_badges(missing_cost) == "🎟️🥚"
    assert max_technology_badges(missing_chance) == "🎟️🥚"
