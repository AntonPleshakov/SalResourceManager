from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from resources import screenshot_storage


def test_delete_stored_screenshot_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot_storage, "SCREENSHOT_DIRECTORY", tmp_path)
    path = screenshot_storage.save_screenshot(b"image", "upload.jpg")
    assert screenshot_storage.delete_screenshot(path)
    assert not Path(path).exists()
    assert not screenshot_storage.delete_screenshot(path)


def test_delete_rejects_unrelated_files_and_other_directories(tmp_path, monkeypatch):
    storage = tmp_path / "screenshots"
    storage.mkdir()
    monkeypatch.setattr(screenshot_storage, "SCREENSHOT_DIRECTORY", storage)
    for path in (storage / "keep.txt", tmp_path / "screenshot_1_abc.jpg"):
        path.write_bytes(b"keep")
        with pytest.raises(ValueError):
            screenshot_storage.delete_screenshot(str(path))
        assert path.read_bytes() == b"keep"


def test_buffer_keeps_latest_100_uploads_including_existing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot_storage, "SCREENSHOT_DIRECTORY", tmp_path)
    existing = tmp_path / f"screenshot_{400:020d}_previous.png"
    existing.write_bytes(b"previous process")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("unrelated")
    paths = [
        Path(screenshot_storage.save_screenshot(str(index).encode(), "upload.jpg"))
        for index in range(103)
    ]
    assert not existing.exists()
    assert all(not path.exists() for path in paths[:3])
    assert all(path.read_bytes() == str(index).encode() for index, path in enumerate(paths) if index >= 3)
    assert len(list(tmp_path.glob("screenshot_*"))) == 100
    assert paths[0].name.startswith(f"screenshot_{401:020d}_")
    assert unrelated.read_text() == "unrelated"


def test_concurrent_uploads_keep_distinct_files_with_a_shared_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(screenshot_storage, "SCREENSHOT_DIRECTORY", tmp_path)

    def upload(index):
        return screenshot_storage.save_screenshot(str(index).encode(), "../../upload.png")

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(upload, range(120)))
    assert len(set(paths)) == 120
    retained = sorted(tmp_path.iterdir())
    assert len(retained) == 100
    assert all(path.parent == tmp_path and path.suffix == ".png" for path in retained)
    assert len({path.read_bytes() for path in retained}) == 100
