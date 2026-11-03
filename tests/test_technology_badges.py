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


def test_max_technology_badges_include_all_completed_groups():
    user = UserData(
        skill_summon_cost=25,
        mount_summon_cost=25,
        extra_mount_chance=50,
        extra_egg_chance=50,
    )

    assert max_technology_badges(user) == "🎟️🐎🥚"


def test_mount_badge_requires_both_mount_technologies():
    missing_cost = UserData(
        mount_summon_cost=24,
        extra_mount_chance=50,
    )
    missing_chance = UserData(
        mount_summon_cost=25,
        extra_mount_chance=49,
    )

    assert "🐎" not in max_technology_badges(missing_cost)
    assert "🐎" not in max_technology_badges(missing_chance)
