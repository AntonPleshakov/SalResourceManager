from resources.screenshot_input import TECH_PATTERNS
from resources.user_data import ResourceField


def field_title(field: ResourceField, language: str = "ru") -> str:
    if language == "ru":
        return field.title
    if field.name == "forge_level":
        return {"ru": field.title, "en": "Forge level", "de": "Schmiedestufe"}[language]
    patterns = TECH_PATTERNS.get(field.name)
    if patterns is None:
        return field.title
    title = patterns[{"en": 0, "ru": 1, "de": 2}[language]].replace("mounts?", "mount")
    return title[0].upper() + title[1:]
