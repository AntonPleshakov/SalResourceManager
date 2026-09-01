from db.database import Database


class DatabaseRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
