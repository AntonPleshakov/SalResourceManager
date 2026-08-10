"""Export the current SQLite user data snapshot to Google Sheets."""

from typing import Iterable

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from logger.app_logger import logger
from resources.user_data import UserData


class GameDataReport:
    HEADER = [UserData().params_views()]

    def __init__(self, sheets: GSheetsManager = None):
        self._sheets = sheets

    def export(self, users: Iterable[UserData]) -> str:
        users = list(users)
        sheets = self._sheets or GSheetsManager()
        spreadsheet = sheets.open(getconf("GAME_DATA_GTABLE_KEY"))
        worksheet_name = getconf("USER_DATA_PAGE_NAME")
        if spreadsheet.is_worksheet_exist(worksheet_name):
            worksheet = spreadsheet.get_worksheet(worksheet_name)
        else:
            worksheet = spreadsheet.add_worksheet(worksheet_name)

        worksheet.ensure_header(self.HEADER)
        worksheet.update_values([user.to_row() for user in users])
        logger.info("Game data report exported: users=%d", len(users))
        return spreadsheet.get_url()
