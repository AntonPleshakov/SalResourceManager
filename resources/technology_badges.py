from resources.user_data import UserData, is_max_technology


SKILLS_BADGE = "🎟️"
MOUNTS_BADGE = "🐎"
PETS_BADGE = "🥚"


def max_technology_badges(user: UserData) -> str:
    """Return badges for player technology groups that reached maximum level."""
    badges = []
    if is_max_technology("skill_summon_cost", user.skill_summon_cost.value):
        badges.append(SKILLS_BADGE)
    if (
        is_max_technology("mount_summon_cost", user.mount_summon_cost.value)
        and is_max_technology("extra_mount_chance", user.extra_mount_chance.value)
    ):
        badges.append(MOUNTS_BADGE)
    if is_max_technology("extra_egg_chance", user.extra_egg_chance.value):
        badges.append(PETS_BADGE)
    return "".join(badges)
