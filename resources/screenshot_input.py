"""Offline icon matching and OCR; screenshots never leave the bot server."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import threading

from resources.user_data import validate_editable_field_value


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
ICON_NAMES = ("mount_keys", "hammers", "skills", "shells", "flasks")
SCREENSHOT_FIELDS = ICON_NAMES + (
    "pets",
    "unmerged_mounts",
    "forge_level", "free_equipment_chance", "skill_summon_cost",
    "extra_egg_chance", "mount_summon_cost", "extra_mount_chance",
)
TECH_PATTERNS = {
    "free_equipment_chance": (
        r"chance to forge equipment for free", r"шанс бесплатно создать снаряжение",
        r"chance, ausrüstung kostenlos zu schmieden",
    ),
    "skill_summon_cost": (
        r"skill summon cost", r"навык призыв стоимость", r"fähigkeit beschwören kosten",
    ),
    "extra_egg_chance": (
        r"chance to summon an extra egg", r"шанс призвать дополнительное яйцо",
        r"chance, ein zusätzliches ei zu beschwören",
    ),
    "mount_summon_cost": (
        r"mounts? summon cost", r"маунты призыв стоимость", r"reittiere beschwören kosten",
    ),
    "extra_mount_chance": (
        r"chance to summon an extra mount", r"шанс призвать дополнительного маунта",
        r"chance, ein zusätzliches reittier zu beschwören",
    ),
}
_OCR_SLOT = threading.BoundedSemaphore(1)


class ScreenshotError(ValueError):
    pass


def tesseract_command() -> str | None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured:
        return shutil.which(configured)
    installed = shutil.which("tesseract")
    if installed:
        return installed
    executable = "tesseract.exe" if os.name == "nt" else "tesseract"
    candidates = (
        Path(sys.prefix) / "tesseract" / executable,
        Path(__file__).resolve().parents[1] / ".venv" / "tesseract" / executable,
    )
    for candidate in candidates:
        resolved = shutil.which(str(candidate))
        if resolved:
            return resolved
    return None


def ocr_available() -> bool:
    return tesseract_command() is not None


def parse_balance(text: str) -> int:
    normalized = re.sub(r"\s+", "", text).casefold().replace(",", ".")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kкmм]?)", normalized)
    if match is None:
        raise ValueError("Не удалось прочитать количество")
    multiplier = {"": 1, "k": 1000, "к": 1000, "m": 1000000, "м": 1000000}[match[2]]
    amount = Decimal(match[1]) * multiplier
    if amount != amount.to_integral_value() or amount > 10**15:
        raise ValueError("Неоднозначное количество")
    return int(amount)


def validate_value(name: str, value: int) -> int:
    if name not in SCREENSHOT_FIELDS or type(value) is not int:
        raise ValueError("Неизвестный показатель")
    if name == "extra_egg_chance" and not 0 <= value <= 50:
        raise ValueError("Шанс дополнительного яйца должен быть от 0 до 50%")
    return validate_editable_field_value(name, value)


def parse_technologies(text: str) -> dict[str, int]:
    candidates: dict[str, set[int]] = {}
    for line in text.casefold().splitlines():
        line = re.sub(r"\s+", " ", line.replace("ё", "е")).strip()
        for name, patterns in TECH_PATTERNS.items():
            for pattern in patterns:
                match = re.fullmatch(pattern + r"\s*[+−–-]?\s*(\d+)\s*%", line)
                if match:
                    try:
                        value = validate_value(name, int(match[1]))
                    except ValueError:
                        continue
                    candidates.setdefault(name, set()).add(value)
    return {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}


def _ocr(image, *, digits: bool = False, psm: int = 6) -> str:
    import cv2

    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ScreenshotError("Не удалось подготовить изображение.")
    executable = tesseract_command()
    if executable is None:
        raise ScreenshotError("Локальное распознавание недоступно. Установите Tesseract.")
    command = [executable, "stdin", "stdout",
               "-l", "eng" if digits else "eng+rus+deu", "--psm", str(psm)]
    if digits:
        command += ["-c", "tessedit_char_whitelist=0123456789.,kKmM"]
    try:
        result = subprocess.run(
            command, input=encoded.tobytes(), capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScreenshotError("Локальное распознавание недоступно. Попробуйте позже.") from error
    if result.returncode:
        raise ScreenshotError("Проверьте установку Tesseract и языков eng/rus/deu на сервере.")
    return result.stdout.decode("utf-8").strip()


@lru_cache(maxsize=8)
def _icon(name: str):
    import cv2
    import numpy as np

    path = Path(__file__).with_name("screenshot_icons") / f"{name}.png"
    return cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)


def _find_icon(image, name: str):
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    # Balances are above the summon buttons; hammers sit below the forge.
    top, bottom = (int(height * .45), height) if name == "hammers" else (0, int(height * .45))
    search = image[top:bottom, :int(width * .7)]
    template = _icon(name)
    mask = None
    if name == "hammers":
        # Ignore the forge/fire behind the invariant hammer silhouette.
        mask = np.zeros(template.shape[:2], dtype=np.uint8)
        outline = np.array([(2, 15), (11, 1), (24, 10), (20, 15),
                            (27, 20), (24, 23), (16, 18), (11, 23)])
        cv2.fillPoly(mask, [outline], 255)
    best = None
    for scale in (.85, .925, 1., 1.075, 1.15):
        candidate = cv2.resize(template, None, fx=scale, fy=scale)
        h, w = candidate.shape[:2]
        if h >= search.shape[0] or w >= search.shape[1]:
            continue
        resized_mask = None if mask is None else cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        scores = cv2.matchTemplate(search, candidate, cv2.TM_CCOEFF_NORMED, mask=resized_mask)
        scores = np.nan_to_num(scores, nan=-1., posinf=-1., neginf=-1.)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if best is None or score > best[0]:
            best = (score, x, y + top, w, h)
    if best is None or best[0] < .80:
        return None
    return best[1:]


def _read_balance(image, position, name: str) -> int | None:
    import cv2

    x, y, w, h = position
    start = x + w + (7 if name == "shells" else 0)
    crop = image[max(0, y - 5):y + h + 6, start:x + w + 115]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Keep white digit interiors, removing the black outline and grey counter.
    readings: dict[int, int] = {}
    for threshold in (180, 190, 200, 220):
        mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)[1]
        # Remove the white area outside the counter. Its curved edge can make
        # OCR lose a decimal point after Telegram JPEG recompression.
        count, labels, components, _ = cv2.connectedComponentsWithStats(mask)
        for index in range(1, count):
            left, top, width, height, _ = components[index]
            if (left == 0 or top == 0 or left + width == mask.shape[1]
                    or top + height == mask.shape[0]):
                mask[labels == index] = 0
        mask = 255 - mask
        mask = cv2.resize(mask, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        mask = cv2.copyMakeBorder(mask, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        try:
            amount = parse_balance(_ocr(mask, digits=True, psm=7))
        except ScreenshotError:
            raise
        except ValueError:
            continue
        readings[amount] = readings.get(amount, 0) + 1
    ranked = sorted(readings, key=readings.get, reverse=True)
    if not ranked or (len(ranked) > 1 and readings[ranked[0]] == readings[ranked[1]]):
        return None
    return ranked[0]


def _read_forge_level(image, position) -> int | None:
    import cv2

    x, y, w, h = position
    # The blue level button is to the right of the hammer counter. Read its
    # lower text row, which contains the level in every interface language.
    crop = image[max(0, y - 31):y, x + 134:min(x + 245, image.shape[1])]
    if not crop.size:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    readings: dict[int, int] = {}
    for threshold in (180, 200, 220):
        mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
        # Separate the trailing number from the translated label at the word gap.
        occupied = (mask == 0).any(axis=0)
        columns = occupied.nonzero()[0]
        if not len(columns):
            continue
        start = int(columns[0])
        for left, right in zip(columns, columns[1:]):
            if right - left >= 5:
                start = int(right)
        mask = mask[:, start:int(columns[-1]) + 1]
        mask = cv2.resize(mask, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        mask = cv2.copyMakeBorder(mask, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        text = _ocr(mask, digits=True, psm=8)
        if not re.fullmatch(r"[0-9]{1,2}", text):
            continue
        level = int(text)
        if 1 <= level <= 35:
            readings[level] = readings.get(level, 0) + 1
    return next((level for level, count in readings.items() if count >= 2), None)


def _selection_panel(image):
    import cv2

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours(
        cv2.inRange(gray, 0, 70), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE,
    )
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (w > width * .7 and height * .1 < h < height * .35
                and y < height * .5 and 1.25 < w / h < 3.5):
            continue
        outline = cv2.approxPolyDP(contour, cv2.arcLength(contour, True) * .02, True)
        if len(outline) != 4:
            continue
        interior = image[y + 5:y + h - 5, x + 5:x + w - 5]
        neutral = (
            (interior.max(axis=2).astype(int) - interior.min(axis=2).astype(int) < 15)
            & (interior[:, :, 0] > 150) & (interior[:, :, 0] < 235)
        )
        coverage = float(neutral.mean())
        if coverage >= .35:
            candidates.append((coverage, (x, y, w, h)))
    # The outer modal can also close above a dark category row; prefer gray fill.
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def _selection_field(image, panel):
    import cv2

    x, y, w, h = panel
    row = image[y + h:y + h + int(h * .4), x:x + w]
    gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
    scores = {}
    for field, icon_names in (
        ("pets", ("selection_pets", "selection_eggs")),
        ("unmerged_mounts", ("selection_mounts",)),
    ):
        best = 0.0
        for icon_name in icon_names:
            template = cv2.cvtColor(_icon(icon_name), cv2.COLOR_BGR2GRAY)
            for scale in (.85, .925, 1., 1.075, 1.15):
                candidate = cv2.resize(template, None, fx=scale, fy=scale)
                if candidate.shape[0] >= gray.shape[0] or candidate.shape[1] >= gray.shape[1]:
                    continue
                # Normalize the background and accept both dark and light glyphs.
                matches = cv2.matchTemplate(gray, candidate, cv2.TM_CCOEFF_NORMED)
                lowest, highest, _, _ = cv2.minMaxLoc(matches)
                best = max(best, abs(lowest), abs(highest))
        scores[field] = best
    ranked = sorted(scores, key=scores.get, reverse=True)
    if scores[ranked[0]] < .8 or scores[ranked[0]] - scores[ranked[1]] < .1:
        return None
    return ranked[0]


def _read_selection_count(image, field, *, panel=None) -> int | None:
    import cv2
    import numpy as np

    panel = panel if panel is not None else _selection_panel(image)
    if panel is None:
        return None
    x, y, w, h = panel
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    crop = gray[y + int(h * .78):y + int(h * .93),
                x + int(w * .03):x + int(w * .45)]
    for psm in (7, 8):
        readings: dict[int, int] = {}
        for threshold in (80, 120, 160):
            mask = cv2.threshold(crop, threshold, 255, cv2.THRESH_BINARY)[1]
            rows, columns = np.where(mask == 0)
            if not len(columns):
                continue
            occupied = np.unique(columns)
            left, right = int(occupied[0]), int(occupied[-1]) + 1
            text_height = int(rows.max() - rows.min() + 1)
            # Read the leading number only; the following label can be any language.
            for previous, current in zip(occupied, occupied[1:]):
                if current - previous >= max(4, text_height * .3):
                    right = int(previous) + 1
                    break
            number = mask[:, left:right]
            if psm == 7:
                number = number[max(0, int(rows.min()) - 2):int(rows.max()) + 3]
            number = cv2.resize(number, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            number = cv2.copyMakeBorder(number, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            text = _ocr(number, digits=True, psm=psm)
            if not re.fullmatch(r"[0-9]+", text):
                continue
            try:
                value = validate_value(field, int(text))
            except ValueError:
                continue
            readings[value] = readings.get(value, 0) + 1
        value = next((value for value, count in readings.items() if count >= 2), None)
        if value is not None:
            return value
    return None


def _recognize(image_bytes: bytes) -> dict[str, int]:
    import cv2
    import numpy as np
    from PIL import Image, UnidentifiedImageError
    from io import BytesIO

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            width, height = source.size
            if (width * height > MAX_IMAGE_PIXELS or min(width, height) < 200
                    or not .3 <= width / height <= 1):
                raise ScreenshotError("Отправьте скриншот без обрезки, до 16 мегапикселей.")
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ScreenshotError("Поддерживаются JPEG, PNG и WebP.")
            source.thumbnail((600, 1600))
            image = cv2.cvtColor(np.array(source.convert("RGB")), cv2.COLOR_RGB2BGR)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ScreenshotError("Не удалось открыть изображение.") from error
    image = cv2.resize(image, (591, round(image.shape[0] * 591 / image.shape[1])))
    selection_panel = _selection_panel(image)
    if selection_panel is not None:
        field = _selection_field(image, selection_panel)
        if field is not None:
            count = _read_selection_count(image, field, panel=selection_panel)
            if count is not None:
                return {field: count}
    values = {}
    for name in ICON_NAMES:
        position = _find_icon(image, name)
        if position is None:
            continue
        amount = _read_balance(image, position, name)
        if amount is not None:
            values[name] = amount
        if name == "hammers":
            level = _read_forge_level(image, position)
            if level is not None:
                values["forge_level"] = level
    height, width = image.shape[:2]
    panel = image[int(height * .25):int(height * .77), int(width * .1):int(width * .9)]
    gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2)
    values.update(parse_technologies(_ocr(enlarged)))
    return values


def recognize_screenshot(image: bytes) -> dict[str, int]:
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ScreenshotError("Отправьте изображение размером до 10 МБ.")
    if not ocr_available():
        raise ScreenshotError("Распознавание пока не настроено администратором.")
    if not _OCR_SLOT.acquire(blocking=False):
        raise ScreenshotError("Распознавание занято. Отправьте скриншот через несколько секунд.")
    try:
        return _recognize(image)
    finally:
        _OCR_SLOT.release()
