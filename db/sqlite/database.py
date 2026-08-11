"""SQLite connection, transactions, and migrations."""

import sqlite3
import threading
from pathlib import Path
from typing import Callable, List, Optional, Sequence, TypeVar

from .migration_runner import apply_migrations


T = TypeVar("T")


class SQLiteDatabase:
    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
        )
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            with self._lock:
                apply_migrations(self._connection)
        except Exception:
            self._connection.close()
            raise

    def fetch_all(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> List[tuple]:
        with self._lock:
            return self._connection.execute(query, parameters).fetchall()

    def fetch_one(
        self,
        query: str,
        parameters: Sequence[object] = (),
    ) -> Optional[tuple]:
        with self._lock:
            return self._connection.execute(query, parameters).fetchone()

    def run_in_transaction(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        with self._lock, self._connection:
            return operation(self._connection)

    def close(self) -> None:
        with self._lock:
            self._connection.close()
