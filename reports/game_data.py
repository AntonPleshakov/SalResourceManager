"""Export the current user-data snapshot to Google Sheets."""

from typing import Iterable

import pygsheets
from pygsheets.client import Client
from pygsheets.exceptions import WorksheetNotFound

from config.config import getconf, getconf_path
from logger.app_logger import logger
from resources.user_data import UserData


class GameDataReport:
    HEADER = [UserData().params_views()]

    def __init__(self, client: Client = None):
        self._client = client

    def export(self, users: Iterable[UserData]) -> str:
        users = list(users)
        client = self._client or pygsheets.authorize(
            service_file=str(getconf_path("GSERVICE_FILE"))
        )
        spreadsheet = client.open_by_key(getconf("GAME_DATA_GTABLE_KEY"))
        worksheet_name = getconf("USER_DATA_PAGE_NAME")
        try:
            worksheet = spreadsheet.worksheet_by_title(worksheet_name)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(worksheet_name)

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
