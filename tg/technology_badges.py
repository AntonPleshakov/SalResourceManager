from resources.technology_badges import (
    ALL_TECHNOLOGIES_BADGE,
    MOUNTS_BADGE,
    PETS_BADGE,
    SKILLS_BADGE,
)
from tg.rich import details


def technology_badges_legend() -> str:
    return details(
        "Обозначения технологий",
        f"<p>{SKILLS_BADGE} — снижение стоимости призыва навыков: 25%.</p>"
        f"<p>{MOUNTS_BADGE} — снижение стоимости призыва маунта: 25% "
        "и шанс дополнительного маунта: 50%.</p>"
        f"<p>{PETS_BADGE} — дополнительный шанс на яйцо: 50%.</p>"
        f"<p>{ALL_TECHNOLOGIES_BADGE} — все четыре перечисленные технологии "
        "на максимуме; заменяет три отдельных значка.</p>",
    )
