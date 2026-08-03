from dataclasses import dataclass
from datetime import date
import re
from typing import Optional, Tuple


@dataclass(frozen=True)
class Release:
    version: str
    released_on: date
    changes: Tuple[str, ...]


RELEASES: Tuple[Release, ...] = (
    Release(
        version="1.0.0",
        released_on=date(2026, 8, 2),
        changes=(
            "Старт бота.",
            "Учет ресурсов пользователей.",
            "Напоминания о необходимости обновить ресурсы.",
            "Калькулятор очков войны.",
        ),
    ),
    Release(
        version="1.0.1",
        released_on=date(2026, 8, 3),
        changes=(
            "Исправлена проверка значений при заполнении всего раздела целиком.",
        ),
    ),
    Release(
        version="1.1.0",
        released_on=date(2026, 8, 3),
        changes=(
            "Добавлен расчёт личных очков войны по ресурсам пользователя.",
        ),
    ),
    Release(
        version="1.2.0",
        released_on=date(2026, 8, 3),
        changes=(
            "Добавлено версионирование бота.",
            "В меню появилась кнопка «Что нового».",
            "Непросмотренные изменения показываются при открытии меню.",
        ),
    ),
)

CURRENT_VERSION = RELEASES[-1].version
_SEMANTIC_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def version_key(version: str) -> Tuple[int, int, int]:
    match = _SEMANTIC_VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"Invalid semantic version: {version}")
    return tuple(int(part) for part in match.groups())


def unseen_releases(last_seen_version: Optional[str]) -> Tuple[Release, ...]:
    """Return missed releases, or only the current release for a new user."""
    if not last_seen_version:
        return RELEASES[-1:]

    try:
        last_seen_key = version_key(last_seen_version)
    except ValueError:
        return RELEASES[-1:]
    return tuple(
        release
        for release in RELEASES
        if version_key(release.version) > last_seen_key
    )


for previous, current in zip(RELEASES, RELEASES[1:]):
    if version_key(previous.version) >= version_key(current.version):
        raise ValueError("Releases must be ordered by ascending semantic version")
