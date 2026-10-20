from io import BytesIO
from pathlib import Path
import subprocess

import pytest

from resources import screenshot_input as recognition


FIXTURES = Path(__file__).with_name("fixtures") / "screenshots"
EXPECTED = [
    {"mount_keys": 70700},
    {"hammers": 194691, "forge_level": 8},
    {"skills": 200000},
    {"shells": 96500},
    {"flasks": 3070},
    {"free_equipment_chance": 17},
    {"skill_summon_cost": 25, "extra_egg_chance": 50},
    {"mount_summon_cost": 23, "extra_mount_chance": 46},
    {"free_equipment_chance": 17},
    {"skill_summon_cost": 25, "extra_egg_chance": 50},
    {"mount_summon_cost": 23, "extra_mount_chance": 46},
]


@pytest.mark.parametrize("text,expected", [
    ("70.7k", 70700), ("194691", 194691), ("200К", 200000),
    ("96,5k", 96500), ("3.07k", 3070), ("1.2m", 1200000),
    ("0", 0), ("1 234", 1234),
])
def test_balance_units(text, expected):
    assert recognition.parse_balance(text) == expected


def test_tesseract_is_found_in_current_virtual_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(recognition.sys, "prefix", str(tmp_path))
    executable = "tesseract.exe" if recognition.os.name == "nt" else "tesseract"
    expected = str(tmp_path / "tesseract" / executable)
    monkeypatch.setattr(recognition.shutil, "which", lambda command: expected if command == expected else None)
    assert recognition.tesseract_command() == expected
    assert recognition.ocr_available()


def test_explicit_tesseract_override_is_not_silently_replaced(monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", "missing-ocr")
    monkeypatch.setattr(recognition.shutil, "which", lambda command: None if command == "missing-ocr" else "installed-ocr")
    assert recognition.tesseract_command() is None


def test_tesseract_on_path_is_preferred_to_local_fallback(monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(recognition.shutil, "which", lambda command: "installed-ocr" if command == "tesseract" else "local-ocr")
    assert recognition.tesseract_command() == "installed-ocr"


@pytest.mark.parametrize("text", ["3.07", "-1", "3k 52", "1/4", "12%", "", "1e4"])
def test_ambiguous_balance_is_rejected(text):
    with pytest.raises(ValueError):
        recognition.parse_balance(text)


def test_only_requested_complete_technology_labels_are_accepted():
    assert recognition.parse_technologies(
        "Forge Upgrade Cost -25%\nHammers Bonus +17%\n"
        "Chance to forge equipment for free +17%\n"
        "Skill Summon Cost -25%\nChance to summon an extra egg +50%\n"
        "Маунты Призыв Стоимость -23%\n"
        "Шанс призвать дополнительного маунта +46%\n"
        "Шанс бесплатно создать снаряжение +\n"
        "Common Egg Hatch Timer Speed +100%\n55.8%"
    ) == {
        "free_equipment_chance": 17, "skill_summon_cost": 25,
        "extra_egg_chance": 50, "mount_summon_cost": 23,
        "extra_mount_chance": 46,
    }


def test_conflicting_and_out_of_range_technology_readings_are_omitted():
    assert recognition.parse_technologies(
        "Skill Summon Cost -23%\nSkill Summon Cost -25%\n"
        "Chance to summon an extra egg +51%"
    ) == {}


def test_german_labels_cover_all_tracked_technology_bonuses():
    values = recognition.parse_technologies(
        "Schmiede Upgrade Kosten -25%\nHämmer Bonus +17%\n"
        "Chance, Ausrüstung kostenlos zu schmieden +17%\n"
        "Fähigkeit Beschwören Kosten -25%\n"
        "Chance, ein zusätzliches Ei zu beschwören +50%\n"
        "Reittiere Beschwören Kosten -23%\n"
        "Chance, ein zusätzliches Reittier zu beschwören +46%\n"
        "Fähigkeits-Tickets Bonus +25%\nTech-Tränke Bonus +22%\n"
        "Gewöhnlich Ei Schlüpfen Timer-Geschwindigkeit +100%"
    )
    assert values == {
        "free_equipment_chance": 17, "skill_summon_cost": 25,
        "extra_egg_chance": 50, "mount_summon_cost": 23, "extra_mount_chance": 46,
    }
    assert set(values) == set(recognition.TECH_PATTERNS)


@pytest.mark.parametrize("name,expected", [
    ("forge", {"free_equipment_chance": 17}),
    ("skills", {"skill_summon_cost": 25, "extra_egg_chance": 50}),
    ("mounts", {"mount_summon_cost": 23, "extra_mount_chance": 46}),
])
def test_german_technology_screenshots(name, expected):
    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    assert recognition.recognize_screenshot(
        (FIXTURES / f"technology_de_{name}.jpg").read_bytes()
    ) == expected


@pytest.mark.parametrize("index", range(1, 12))
def test_supplied_screenshots(index):
    if not recognition.ocr_available():
        pytest.skip("Install Tesseract with eng, rus and deu to run image regression tests")
    assert recognition.recognize_screenshot(
        (FIXTURES / f"screen_{index:02}.png").read_bytes()
    ) == EXPECTED[index - 1]


def test_flasks_in_actual_telegram_download():
    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    assert recognition.recognize_screenshot(
        (FIXTURES / "screen_05_telegram.jpg").read_bytes()
    ) == {"flasks": 3070}


@pytest.mark.parametrize("index", range(1, 6))
@pytest.mark.parametrize("width", [400, 900])
def test_resources_after_resizing_and_telegram_jpeg_compression(index, width):
    from PIL import Image

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    with Image.open(FIXTURES / f"screen_{index:02}.png") as image:
        resized = image.resize((width, round(image.height * width / image.width)))
        stream = BytesIO()
        resized.convert("RGB").save(stream, format="JPEG", quality=80)
    assert recognition.recognize_screenshot(stream.getvalue()) == EXPECTED[index - 1]


def test_oversize_image_is_rejected_before_decoding():
    with pytest.raises(recognition.ScreenshotError, match="10"):
        recognition.recognize_screenshot(b"x" * (recognition.MAX_IMAGE_BYTES + 1))


def test_hammer_recognition_does_not_depend_on_forge_or_fire_background():
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    image = cv2.imdecode(np.frombuffer((FIXTURES / "screen_02.png").read_bytes(), dtype=np.uint8), 1)
    image[925:1005, 220:375] = (180, 80, 30)
    mask = np.zeros((24, 28), dtype=np.uint8)
    outline = np.array([(2, 15), (11, 1), (24, 10), (20, 15),
                        (27, 20), (24, 23), (16, 18), (11, 23)])
    cv2.fillPoly(mask, [outline], 255)
    image[1008:1032, 244:272][mask == 0] = (180, 80, 30)
    success, encoded = cv2.imencode(".png", image)
    assert success
    assert recognition.recognize_screenshot(encoded.tobytes())["hammers"] == 194691


def test_ocr_timeout_is_reported(monkeypatch):
    import numpy as np

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 15)

    monkeypatch.setattr(subprocess, "run", timeout)
    monkeypatch.setattr(recognition, "tesseract_command", lambda: "tesseract")
    with pytest.raises(recognition.ScreenshotError):
        recognition._ocr(np.zeros((30, 60), dtype=np.uint8))


def test_blank_and_invalid_images(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(recognition, "ocr_available", lambda: True)
    with pytest.raises(recognition.ScreenshotError):
        recognition.recognize_screenshot(b"not an image")
    if not recognition.tesseract_command():
        return
    stream = BytesIO()
    Image.new("RGB", (591, 1280), "white").save(stream, format="PNG")
    assert recognition.recognize_screenshot(stream.getvalue()) == {}


@pytest.mark.parametrize("label", ["", "Stufe", "Nivel"])
def test_forge_level_does_not_require_localized_button_label(label):
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    image = cv2.imdecode(np.frombuffer((FIXTURES / "screen_02.png").read_bytes(), dtype=np.uint8), 1)
    # Preserve only the digit 8, replacing both localized text fragments.
    image[960:980, 400:475] = (230, 170, 0)
    image[980:1002, 398:456] = (230, 170, 0)
    cv2.putText(image, label, (398, 997), cv2.FONT_HERSHEY_SIMPLEX,
                .45, (255, 255, 255), 1, cv2.LINE_AA)
    success, encoded = cv2.imencode(".png", image)
    assert success
    assert recognition.recognize_screenshot(encoded.tobytes()) == EXPECTED[1]


@pytest.mark.parametrize("readings", [
    ["8", "9", ""], ["0", "0", "0"], ["36", "36", "36"],
    ["8.0", "8.0", "8.0"], ["8 9", "8 9", "8 9"],
])
def test_forge_level_omits_ambiguous_or_invalid_readings(monkeypatch, readings):
    import numpy as np

    results = iter(readings)
    monkeypatch.setattr(recognition, "_ocr", lambda *args, **kwargs: next(results))
    assert recognition._read_forge_level(
        np.full((200, 400, 3), 255, dtype=np.uint8), (100, 150, 28, 24),
    ) is None


@pytest.mark.parametrize("filename,field,count", [("pets_selected_96.jpg", "pets", 96), ("mounts_selected_357.jpg", "unmerged_mounts", 357), ("pets_selected_1658.jpg", "pets", 1658)])
@pytest.mark.parametrize("width", [400, 591, 900])
def test_selection_count_from_actual_telegram_screenshot(filename, field, count, width):
    from PIL import Image

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    with Image.open(FIXTURES / filename) as image:
        resized = image.resize((width, round(image.height * width / image.width)))
        stream = BytesIO()
        resized.save(stream, format="JPEG", quality=80)
    assert recognition.recognize_screenshot(stream.getvalue()) == {field: count}


@pytest.mark.parametrize("filename,field,count,label_left", [("pets_selected_96.jpg", "pets", 96, 94), ("mounts_selected_357.jpg", "unmerged_mounts", 357, 104), ("pets_selected_1658.jpg", "pets", 1658, 114)])
@pytest.mark.parametrize("label", ["", "selected", "ausgewaehlt", "choisis"])
def test_selection_count_does_not_depend_on_localized_label(filename, field, count, label_left, label):
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    image = cv2.imdecode(np.frombuffer((FIXTURES / filename).read_bytes(), np.uint8), 1)
    # Preserve the real number and replace only its following label.
    image[380:420, label_left:300] = (222, 222, 222)
    cv2.putText(image, label, (label_left + 2, 405), cv2.FONT_HERSHEY_SIMPLEX,
                .6, (0, 0, 0), 2, cv2.LINE_AA)
    success, encoded = cv2.imencode(".png", image)
    assert success
    assert recognition.recognize_screenshot(encoded.tobytes()) == {field: count}


@pytest.mark.parametrize("count", [0, 1, 12, 9999])
def test_pet_count_reads_only_the_number_in_the_panel(count):
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    image = cv2.imdecode(np.frombuffer((FIXTURES / "pets_selected_96.jpg").read_bytes(), np.uint8), 1)
    image[380:420, 60:300] = (222, 222, 222)
    cv2.putText(image, f"{count} selected", (64, 405), cv2.FONT_HERSHEY_SIMPLEX,
                .65, (0, 0, 0), 2, cv2.LINE_AA)
    assert recognition._read_selection_count(image, "pets") == count


@pytest.mark.parametrize("readings", [["96", "97", ""], ["-1", "-1", "-1"], ["9.6", "9.6", "9.6"]])
def test_pet_count_omits_ambiguous_and_invalid_ocr_readings(monkeypatch, readings):
    import cv2
    import numpy as np

    results = iter(readings * 2)
    monkeypatch.setattr(recognition, "_ocr", lambda *args, **kwargs: next(results))
    image = cv2.imdecode(np.frombuffer((FIXTURES / "pets_selected_96.jpg").read_bytes(), np.uint8), 1)
    assert recognition._read_selection_count(image, "pets") is None


@pytest.mark.parametrize("line_readings,word_readings,expected", [
    (["387", "357", "387"], ["357", "357", "357"], 357),
    (["357", "357", "357"], ["387", "357", "387"], 357),
    (["387", "387", "387"], ["357", "357", "357"], None),
    (["", "", ""], ["0", "0", "0"], 0),
])
def test_selection_count_compares_both_ocr_modes_before_accepting_consensus(
    monkeypatch, line_readings, word_readings, expected,
):
    import cv2
    import numpy as np

    results = {7: iter(line_readings), 8: iter(word_readings)}
    monkeypatch.setattr(recognition, "_ocr", lambda *args, psm, **kwargs: next(results[psm]))
    image = cv2.imdecode(np.frombuffer((FIXTURES / "mounts_selected_357.jpg").read_bytes(), np.uint8), 1)
    assert recognition._read_selection_count(image, "unmerged_mounts") == expected


@pytest.mark.parametrize("mounts", [False, True])
def test_selection_type_follows_category_icons_instead_of_number_or_label(mounts):
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    pets = cv2.imdecode(np.frombuffer((FIXTURES / "pets_selected_96.jpg").read_bytes(), np.uint8), 1)
    mount_image = cv2.imdecode(np.frombuffer((FIXTURES / "mounts_selected_357.jpg").read_bytes(), np.uint8), 1)
    image, replacement = (pets, mount_image) if mounts else (mount_image, pets)
    image[438:540] = replacement[438:540]
    success, encoded = cv2.imencode(".png", image)
    assert success
    assert recognition.recognize_screenshot(encoded.tobytes()) == {
        "unmerged_mounts" if mounts else "pets": 96 if mounts else 357,
    }


@pytest.mark.parametrize("ambiguous", [False, True])
def test_unknown_or_conflicting_category_icons_do_not_select_a_resource(ambiguous):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer((FIXTURES / "pets_selected_96.jpg").read_bytes(), np.uint8), 1)
    if ambiguous:
        mounts = cv2.imdecode(np.frombuffer((FIXTURES / "mounts_selected_357.jpg").read_bytes(), np.uint8), 1)
        image[466:500, 400:436] = mounts[467:501, 114:150]
    else:
        image[438:540] = 255
    assert recognition._selection_field(image, recognition._selection_panel(image)) is None


@pytest.mark.parametrize("filename,field,count,box", [
    ("pets_selected_96.jpg", "pets", 96, (245, 466, 34, 32)),
    ("pets_selected_1658.jpg", "pets", 1658, (150, 465, 29, 32)),
    ("mounts_selected_357.jpg", "unmerged_mounts", 357, (114, 467, 36, 34)),
])
@pytest.mark.parametrize("background", [
    (255, 255, 255), (0, 0, 0), (255, 0, 0),
    (0, 255, 0), (0, 0, 255), (60, 100, 180),
])
def test_selection_icons_are_recognized_on_different_backgrounds(filename, field, count, box, background):
    import cv2
    import numpy as np

    if not recognition.ocr_available():
        pytest.skip("Tesseract unavailable")
    image = cv2.imdecode(np.frombuffer((FIXTURES / filename).read_bytes(), np.uint8), 1)
    x, y, w, h = box
    glyph = cv2.cvtColor(image[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
    _, foreground = cv2.threshold(glyph, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # Remove all rarity cards and leave just one glyph on a new background.
    image[438:540] = background
    icon = image[465:465 + h, 230:230 + w]
    shade = 60 if np.mean(background) > 120 else 220
    icon[foreground != 0] = (shade, shade, shade)
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert success
    assert recognition.recognize_screenshot(encoded.tobytes()) == {field: count}
