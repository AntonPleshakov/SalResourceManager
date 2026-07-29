from typing import Dict

from pygsheets.spreadsheet import Spreadsheet
from pygsheets.worksheet import Worksheet

from logger.app_logger import logger as nmd_logger
from .worksheet_manager import WorksheetManager

DEFAULT_WORKSHEET_NAME = "Sheet1"


class SpreadsheetManager:
    def __init__(self, spreadsheet: Spreadsheet):
        self._ss: Spreadsheet = spreadsheet
        self._cache: Dict[str, Worksheet] = dict()

    def _get_cached_ws(self, worksheet_title: str) -> Worksheet:
        if worksheet_title not in self._cache:
            self._cache[worksheet_title] = self._ss.worksheet_by_title(worksheet_title)
        return self._cache[worksheet_title]

    def make_public(self):
        self._ss.share("", "reader", "anyone")

    def get_worksheet(self, worksheet_title: str) -> WorksheetManager:
        ws_manager = WorksheetManager(self._get_cached_ws(worksheet_title))
        return ws_manager

    def is_worksheet_exist(self, worksheet_title: str) -> bool:
        worksheets = self._ss.worksheets()
        return any(ws.title == worksheet_title for ws in worksheets)

    def add_worksheet(self, worksheet_title: str) -> WorksheetManager:
        nmd_logger.info(f"GAPI: '{self._ss.title}' add ws '{worksheet_title}'")
        ws = self._ss.add_worksheet(worksheet_title, index=0)
        self._cache[worksheet_title] = ws
        return WorksheetManager(ws)

    def delete_worksheet(self, worksheet_title: str):
        nmd_logger.info(f"GAPI: '{self._ss.title}' delete ws '{worksheet_title}'")
        ws = self._ss.worksheet_by_title(worksheet_title)
        self._ss.del_worksheet(ws)
        self._cache.pop(worksheet_title)

    def rename_worksheet(
        self, new_name: str, old_name: str = DEFAULT_WORKSHEET_NAME
    ) -> WorksheetManager:
        nmd_logger.info(
            f"GAPI: '{self._ss.title}' rename ws '{old_name}' -> '{new_name}'"
        )
        ws = self._get_cached_ws(old_name)
        ws.title = new_name
        self._cache.pop(old_name)
        self._cache[new_name] = ws
        return WorksheetManager(ws)

    def get_url(self) -> str:
        return self._ss.url
