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
    Release(
        version="1.3.0",
        released_on=date(2026, 8, 3),
        changes=(
            "В калькуляторе войны добавлена разбивка очков по дням и активностям.",
            "Для каждой активности доступен подробный расчёт с ресурсами, "
            "промежуточными значениями и формулой.",
        ),
    ),
    Release(
        version="1.4.0",
        released_on=date(2026, 8, 3),
        changes=(
            "Дневной отчёт показывает независимый максимум, а итог по "
            "активностям учитывает расходование ресурсов.",
            "Расчёт кузницы учитывает повышение уровня между вторым и "
            "четвёртым днями войны.",
            "Исправлены очки навыков: теперь они начисляются за созданные "
            "навыки, а не за потраченные билетики.",
        ),
    ),
    Release(
        version="1.5.0",
        released_on=date(2026, 8, 10),
        changes=(
            "Google таблицы заменены на локальную SQLite базу данных (это улучшит производительность и сократит издержки).",
            "Добавлены настройки питомцев: количество яиц в пакете, максимальный уровень яйца и "
            "количество ежедневных пакетов для вылупления.",
            "Обновлены напоминания о заполнении данных и навигация по меню.",
            "Бесконечный polling заменён на webhook, что улучшает стабильность работы бота.",
        ),
    ),
    Release(
        version="1.6.0",
        released_on=date(2026, 8, 11),
        changes=(
            "Добавлена поддержка нескольких игровых аккаунтов, включая твинков.",
            "В стартовое меню добавлены команды для навигации.",
        ),
    ),
    Release(
        version="1.7.0",
        released_on=date(2026, 8, 14),
        changes=(
            "Масштабно обновлены интерфейс и пользовательский опыт: переработаны меню, навигация и сценарии взаимодействия с ботом.",
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
    """Return missed releases, or up to five recent releases for a new user."""
    if not last_seen_version:
        return RELEASES[-5:]

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
