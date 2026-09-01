"""Export the current user-data snapshot to Google Sheets."""

from pathlib import Path
from typing import Iterable

import pygsheets
from pygsheets.client import Client
from pygsheets.exceptions import WorksheetNotFound

from common.datetime_utils import format_last_update
from config.config import getconf
from logger.app_logger import logger
from resources.user_data import UPDATED_AT_FIELDS, UserData


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOOGLE_SERVICE_FILE = _PROJECT_ROOT / "gapi_service_file.json"
USER_DATA_PAGE_NAME = "User data"
_TRACKED_FIELD_BY_UPDATE_FIELD = {
    update_field: tracked_field
    for tracked_field, update_field in UPDATED_AT_FIELDS.items()
}


class GameDataReport:
    HEADER = [UserData().params_views()]

    def __init__(self, client: Client = None):
        self._client = client

    @staticmethod
    def _escape_formulas(row: list[str]) -> list[str]:
        return [
            f"'{value}" if value.startswith(("=", "+")) else value
            for value in row
        ]

    @staticmethod
    def _to_report_row(user: UserData) -> list[str]:
        row = user.to_row()
        for index, parameter_name in enumerate(user.params()):
            tracked_field = _TRACKED_FIELD_BY_UPDATE_FIELD.get(parameter_name)
            if tracked_field is None:
                continue
            updated_on = user.get_updated_on(tracked_field)
            row[index] = format_last_update(updated_on)
        return row

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

        rows = self.HEADER + [
            self._escape_formulas(self._to_report_row(user))
            for user in users
        ]
        worksheet.clear()
        worksheet.update_values("A1", rows, extend=True)
        worksheet.show_dimensions(1, worksheet.cols, dimension="COLUMNS")
        worksheet.frozen_rows = len(self.HEADER)
        logger.info("Game data report exported: users=%d", len(users))
        return spreadsheet.url
