"""Export the current user-data snapshot to Google Sheets."""

from pathlib import Path
from typing import Iterable

import pygsheets
from pygsheets.client import Client
from pygsheets.exceptions import WorksheetNotFound

from config.config import getconf
from logger.app_logger import logger
from resources.user_data import UserData


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOOGLE_SERVICE_FILE = _PROJECT_ROOT / "gapi_service_file.json"
USER_DATA_PAGE_NAME = "User data"


class GameDataReport:
    HEADER = [UserData().params_views()]

    def __init__(self, client: Client = None):
        self._client = client

    def export(self, users: Iterable[UserData]) -> str:
        users = list(users)
        client = self._client or pygsheets.authorize(
            service_file=str(GOOGLE_SERVICE_FILE)
        )
        spreadsheet = client.open_by_key(getconf("GAME_DATA_GTABLE_KEY"))
        try:
            worksheet = spreadsheet.worksheet_by_title(USER_DATA_PAGE_NAME)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(USER_DATA_PAGE_NAME)

        rows = self.HEADER + [self._escape_formulas(user.to_row()) for user in users]
        worksheet.clear()
        worksheet.update_values("A1", rows, extend=True)
        worksheet.show_dimensions(1, worksheet.cols, dimension="COLUMNS")
        worksheet.frozen_rows = len(self.HEADER)
        logger.info("Game data report exported: users=%d", len(users))
        return spreadsheet.url

    @staticmethod
    def _escape_formulas(row: list[str]) -> list[str]:
        return [
            f"'{value}" if value.startswith(("=", "+")) else value
            for value in row
        ]
