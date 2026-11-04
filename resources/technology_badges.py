from resources.user_data import UserData, is_max_technology


SKILLS_BADGE = "🎟️"
MOUNTS_BADGE = "🐎"
PETS_BADGE = "🥚"
ALL_TECHNOLOGIES_BADGE = "🏆"


def max_technology_groups(user: UserData) -> tuple[str, ...]:
    groups = []
    if is_max_technology("skill_summon_cost", user.skill_summon_cost.value):
        groups.append("skills")
    if (
        is_max_technology("mount_summon_cost", user.mount_summon_cost.value)
        and is_max_technology("extra_mount_chance", user.extra_mount_chance.value)
    ):
        groups.append("mounts")
    if is_max_technology("extra_egg_chance", user.extra_egg_chance.value):
        groups.append("pets")
    return tuple(groups)


def matches_technology_filter(user: UserData, technology: str) -> bool:
    if technology == "any":
        return True
    groups = max_technology_groups(user)
    return len(groups) == 3 if technology == "all" else technology in groups


def max_technology_badges(user: UserData) -> str:
    """Return badges for player technology groups that reached maximum level."""
    groups = max_technology_groups(user)
    if len(groups) == 3:
        return ALL_TECHNOLOGIES_BADGE
    icons = {"skills": SKILLS_BADGE, "mounts": MOUNTS_BADGE, "pets": PETS_BADGE}
    return "".join(icons[group] for group in groups)
