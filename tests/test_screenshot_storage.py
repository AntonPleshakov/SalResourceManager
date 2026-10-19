from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from resources import screenshot_storage


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
