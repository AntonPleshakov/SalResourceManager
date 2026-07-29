import time
from pathlib import Path

import pytest

from db.gapi.gdrive_manager import GDriveManager


@pytest.fixture
def manager():
    return GDriveManager()


@pytest.mark.gdrive_access
@pytest.mark.parametrize(
    "file_path, is_exist", [("test.txt", True), ("test2.txt", False)]
)
def test_file_existence(manager: GDriveManager, file_path: str, is_exist: bool):
    assert manager.is_file_exists(file_path) == is_exist


@pytest.mark.gdrive_access
@pytest.mark.slow
def test_file_creation(manager: GDriveManager, tmp_path: Path):
    file_name = "test2.txt"
    file_path = tmp_path / file_name
    assert not manager.is_file_exists(file_name)

    # Create a file to upload
    original_content = "123"
    with open(file_path, "w") as file:
        file.write(original_content)
    manager.upload_file(str(file_path), file_name)
    cnt = 0
    while (not manager.is_file_exists(file_name)) and (cnt < 20):
        time.sleep(0.1)
        cnt += 1
    assert cnt < 20

    # Rewrite the content of file
    new_content = "456"
    with open(file_path, "w") as f:
        f.write(new_content)
    manager.download_file(file_name, str(file_path))
    with open(file_path, "r") as f:
        result_content = f.read()
    assert result_content == original_content

    # Delete the file from gdrive
    manager.delete_file(file_name)
    assert not manager.is_file_exists(file_name)


@pytest.mark.gdrive_access
def test_file_renaming(manager: GDriveManager):
    old_name = "test.txt"
    new_name = "test2.txt"
    assert manager.is_file_exists(old_name)
    assert not manager.is_file_exists(new_name)

    manager.rename_file(old_name, new_name)
    assert not manager.is_file_exists(old_name)
    assert manager.is_file_exists(new_name)

    manager.rename_file(new_name, old_name)
    assert manager.is_file_exists(old_name)
    assert not manager.is_file_exists(new_name)
