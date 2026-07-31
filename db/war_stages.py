from typing import Dict, Optional, Tuple

from config.config import getconf
from db.gapi.gsheets_manager import GSheetsManager
from db.gapi.worksheet_manager import WorksheetManager
from db.retry import ReconnectableDB
from logger.app_logger import logger
from resources.war import DEFAULT_WAR_STAGES, WarActivity, WarStage


class WarStagesDB(ReconnectableDB):
    HEADER = [["День", "Активность 1", "Активность 2", "Активность 3"]]

    def __init__(self, manager: WorksheetManager):
        self._manager = manager
        self._stages: Dict[int, WarStage] = {}
        self.fetch()

    @classmethod
    def _open_manager(cls) -> WorksheetManager:
        spreadsheet = GSheetsManager().open(getconf("GAME_DATA_GTABLE_KEY"))
        worksheet_name = getconf("WAR_STAGES_PAGE_NAME")
        if spreadsheet.is_worksheet_exist(worksheet_name):
            manager = spreadsheet.get_worksheet(worksheet_name)
        else:
            manager = spreadsheet.add_worksheet(worksheet_name)
            manager.set_header(cls.HEADER)
            manager.update_values(cls._stages_to_rows(DEFAULT_WAR_STAGES))
        return manager

    @classmethod
    def connect(cls) -> "WarStagesDB":
        return cls(cls._open_manager())

    def _reconnect(self) -> None:
        self._manager = self._open_manager()

    def fetch(self) -> None:
        logger.info("DB: fetch war stages")
        def load_stages() -> Dict[int, WarStage]:
            self._manager.fetch()
            stages = dict(DEFAULT_WAR_STAGES)
            for row in self._manager.get_all_values():
                try:
                    day = int(row[0])
                    activities = tuple(
                        WarActivity.from_storage(value) for value in row[1:4]
                    )
                    if day not in DEFAULT_WAR_STAGES or len(activities) != 3:
                        continue
                    stages[day] = activities
                except (IndexError, ValueError):
                    continue
            return stages

        self._stages = self._run_with_retry(load_stages)

    def get_stages(self) -> Dict[int, WarStage]:
        return dict(self._stages)

    def set_activity(self, day: int, position: int, activity: WarActivity) -> None:
        if day not in self._stages:
            raise ValueError(f"Unknown war day: {day}")
        if position not in range(3):
            raise ValueError(f"Unknown activity position: {position}")

        stage = list(self._stages[day])
        stage[position] = activity
        self._stages[day] = tuple(stage)
        self._persist()
        logger.info("DB: set war day %s activity %s to %s", day, position, activity)

    def _persist(self) -> None:
        self._run_with_retry(
            lambda: self._manager.update_values(self._stages_to_rows(self._stages))
        )

    @staticmethod
    def _stages_to_rows(stages: Dict[int, WarStage]):
        return [
            [str(day), *(activity.title for activity in activities)]
            for day, activities in sorted(stages.items())
        ]


war_stages_db: Optional[WarStagesDB] = None


def initialize_war_stages_db() -> WarStagesDB:
    global war_stages_db
    war_stages_db = WarStagesDB.connect()
    return war_stages_db


def get_war_stages_db() -> WarStagesDB:
    if war_stages_db is None:
        raise RuntimeError("War stages database has not been initialized")
    return war_stages_db
