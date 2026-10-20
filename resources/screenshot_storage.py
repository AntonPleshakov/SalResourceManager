"""Keep the latest uploaded screenshots in a bounded, persistent directory."""

from pathlib import Path
import re
import threading
from uuid import uuid4


SCREENSHOT_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "screenshots"
SCREENSHOT_LIMIT = 100
_LOCK = threading.Lock()


def save_screenshot(image: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".img"
    with _LOCK:
        directory = SCREENSHOT_DIRECTORY.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        previous = sorted(directory.glob("screenshot_[0-9]*_*.*"))
        sequence = int(previous[-1].name.split("_")[1]) + 1 if previous else 1
        path = directory / f"screenshot_{sequence:020d}_{uuid4().hex}{suffix}"
        path.write_bytes(image)
        for expired in previous[:max(0, len(previous) + 1 - SCREENSHOT_LIMIT)]:
            expired.unlink()
        return str(path)


def delete_screenshot(filename: str) -> bool:
    with _LOCK:
        path = Path(filename)
        if path.is_symlink():
            raise ValueError("Screenshot must not be a symlink")
        path = path.resolve()
        if (path.parent != SCREENSHOT_DIRECTORY.resolve()
                or re.fullmatch(r"screenshot_[0-9]+_[a-f0-9]+\.(jpg|jpeg|png|webp|img)", path.name) is None):
            raise ValueError("File is outside screenshot storage")
        existed = path.is_file()
        path.unlink(missing_ok=True)
        return existed
