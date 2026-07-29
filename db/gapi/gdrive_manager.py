import json
import os
from typing import Optional, Dict

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from pydrive2.files import GoogleDriveFile

from config.config import getconf


class GDriveManager:
    def __init__(self):
        with open("gapi_service_file.json", "r") as service_file:
            service_dict = json.load(service_file)
        gauth_settings = {
            "service_config": {
                "client_json_dict": service_dict,
                "client_user_email": getconf("GSERVICE_EMAIL"),
            }
        }
        gauth = GoogleAuth(settings=gauth_settings)
        gauth.ServiceAuth()
        self._drive: GoogleDrive = GoogleDrive(gauth)
        self._files: Dict[str, GoogleDriveFile] = {}
        self._folder_path: str = getconf("GDRIVE_FOLDER_PATH")

    def _create_file(self, file_name: str) -> GoogleDriveFile:
        file = self._drive.CreateFile(
            {"parents": [{"id": self._folder_path}], "title": file_name}
        )
        self._files[file_name] = file

        return file

    def _get_file(self, file_name: str) -> Optional[GoogleDriveFile]:
        param = {"q": f"title='{file_name}' and '{self._folder_path}' in parents"}
        files_result = self._drive.ListFile(param).GetList()
        if not files_result:
            return None

        file = files_result[0]
        self._files[file_name] = file
        return file

    def _file(self, file_name) -> GoogleDriveFile:
        if file_name in self._files:
            return self._files[file_name]

        file = self._get_file(file_name)
        if file:
            return file
        else:
            return self._create_file(file_name)

    def rename_file(self, old_name: str, new_name: str):
        file = self._file(old_name)
        file["title"] = new_name
        file.Upload()

        self._files[new_name] = self._files.pop(old_name)

    def delete_file(self, file_name: str):
        file = self._file(file_name)
        file.Delete()

        self._files.pop(file_name)

    def is_file_exists(self, file_name: str) -> bool:
        param = {"q": f"title='{file_name}' and '{self._folder_path}' in parents"}
        files_result = self._drive.ListFile(param).GetList()
        return len(files_result) > 0

    def download_file(self, gdrive_path: str, local_path: str):
        file = self._file(gdrive_path)
        file.GetContentFile(local_path)

    def upload_file(self, file_path: str, gdrive_file_name: str = ""):
        file = self._file(
            gdrive_file_name if gdrive_file_name else os.path.basename(file_path)
        )
        file.SetContentFile(file_path)
        file.Upload()
