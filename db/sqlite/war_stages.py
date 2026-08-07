"""SQLite-backed war-stage storage with Google Sheets dual-write."""

from typing import Dict, Mapping, Sequence

from db.war_stages import WarStagesDB as GoogleWarStagesDB
from resources.war import WarActivity, WarStage

from .database import SQLiteDatabase


class WarStagesDB:
    def __init__(self, database: SQLiteDatabase, google: GoogleWarStagesDB):
        self._database = database
        self._google = google

    def get_stages(self) -> Dict[int, WarStage]:
        rows = self._database.fetch_all(
            "SELECT day, activity_1, activity_2, activity_3 "
            "FROM war_stages ORDER BY day"
        )
        return {
            day: tuple(
                WarActivity.from_storage(value) for value in activities
            )
            for day, *activities in rows
        }

    def set_activity(
        self, day: int, position: int, activity: WarActivity
    ) -> None:
        self._google.set_activity(day, position, activity)
        self.replace_all(self._google.get_stages())

    def replace_all(
        self,
        war_stages: Mapping[int, Sequence[WarActivity]],
    ) -> None:
        rows = tuple(
            (
                int(day),
                *(str(activity.value) for activity in activities),
            )
            for day, activities in sorted(war_stages.items())
        )

        def replace(connection) -> None:
            connection.execute("DELETE FROM war_stages")
            if rows:
                connection.executemany(
                    "INSERT INTO war_stages "
                    "(day, activity_1, activity_2, activity_3) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )

        self._database.run_in_transaction(replace)
