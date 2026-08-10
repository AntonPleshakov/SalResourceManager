from enum import IntEnum


class EggLevel(IntEnum):
    COMMON = 1
    RARE = 2
    EPIC = 3
    LEGENDARY = 4
    ULTIMATE = 5
    MYTHIC = 6

    @property
    def english_name(self) -> str:
        return {
            EggLevel.COMMON: "Common",
            EggLevel.RARE: "Rare",
            EggLevel.EPIC: "Epic",
            EggLevel.LEGENDARY: "Legendary",
            EggLevel.ULTIMATE: "Ultimate",
            EggLevel.MYTHIC: "Mythic",
        }[self]

    @property
    def russian_name(self) -> str:
        return {
            EggLevel.COMMON: "Обычное",
            EggLevel.RARE: "Редкое",
            EggLevel.EPIC: "Эпическое",
            EggLevel.LEGENDARY: "Легендарное",
            EggLevel.ULTIMATE: "Высшее",
            EggLevel.MYTHIC: "Мифическое",
        }[self]

    @property
    def color_icon(self) -> str:
        return {
            EggLevel.COMMON: "🩶",
            EggLevel.RARE: "💙",
            EggLevel.EPIC: "💚",
            EggLevel.LEGENDARY: "💛",
            EggLevel.ULTIMATE: "❤️",
            EggLevel.MYTHIC: "💜",
        }[self]

    @property
    def label(self) -> str:
        return (
            f"{self.color_icon} {self.english_name} / {self.russian_name}"
        )

    @property
    def points(self) -> int:
        return {
            EggLevel.COMMON: 720,
            EggLevel.RARE: 2_880,
            EggLevel.EPIC: 5_760,
            EggLevel.LEGENDARY: 11_520,
            EggLevel.ULTIMATE: 23_040,
            EggLevel.MYTHIC: 46_080,
        }[self]

    @property
    def batch_field_name(self) -> str:
        return f"hatch_batches_{self.name.lower()}"


EGG_LEVELS = tuple(EggLevel)


def format_hatch_batch_count(count: int) -> str:
    remainder_100 = count % 100
    remainder_10 = count % 10
    if remainder_10 == 1 and remainder_100 != 11:
        word = "пакет"
    elif remainder_10 in {2, 3, 4} and not 12 <= remainder_100 <= 14:
        word = "пакета"
    else:
        word = "пакетов"
    return f"{count} {word}"
