"""Discover and transactionally apply ordered SQLite migrations."""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from logger.app_logger import logger


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_NAME = re.compile(r"(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql")
TRANSACTION_STATEMENTS = frozenset({"BEGIN", "COMMIT", "END", "ROLLBACK"})


class MigrationError(RuntimeError):
    """The migration history is invalid or a migration could not be applied."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.version:04d}_{self.name}"


def load_migrations(directory: Path = MIGRATIONS_DIR) -> Tuple[Migration, ...]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                path=path,
            )
        )

    if not migrations:
        raise MigrationError(f"No SQLite migrations found in {directory}")

    versions = tuple(migration.version for migration in migrations)
    expected_versions = tuple(range(1, len(migrations) + 1))
    if versions != expected_versions:
        raise MigrationError(
            f"SQLite migration versions must be continuous: "
            f"found {versions!r}, expected {expected_versions!r}"
        )
    return tuple(migrations)


def apply_migrations(
    connection: sqlite3.Connection,
    directory: Path = MIGRATIONS_DIR,
) -> Tuple[Migration, ...]:
    migrations = load_migrations(directory)
    latest_version = migrations[-1].version
    applied = []

    while True:
        migration = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_version = _get_user_version(connection)
            if current_version < 0:
                raise MigrationError(
                    f"SQLite schema version must not be negative: {current_version}"
                )
            if current_version > latest_version:
                raise MigrationError(
                    f"SQLite schema version {current_version} is newer than "
                    f"supported version {latest_version}"
                )
            if current_version == latest_version:
                connection.commit()
                return tuple(applied)

            migration = migrations[current_version]
            logger.info("SQLite: applying migration %s", migration.label)
            for statement in _read_statements(migration.path):
                _validate_statement(statement, migration)
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except Exception as error:
            if connection.in_transaction:
                connection.rollback()
            if isinstance(error, MigrationError):
                raise
            if migration is None:
                raise
            raise MigrationError(
                f"SQLite migration {migration.label} failed: {error}"
            ) from error

        applied.append(migration)
        logger.info("SQLite: migration %s applied", migration.label)


def _get_user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _read_statements(path: Path) -> Tuple[str, ...]:
    script = path.read_text(encoding="utf-8")
    statements = []
    buffer = ""
    for character in script:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""

    if _strip_comments(buffer).strip():
        raise MigrationError(
            f"Migration {path.name} contains an incomplete SQL statement"
        )
    return tuple(statement for statement in statements if _strip_comments(statement))


def _validate_statement(statement: str, migration: Migration) -> None:
    normalized = _strip_comments(statement).lstrip()
    first_word = normalized.partition(" ")[0].rstrip(";").upper()
    if first_word in TRANSACTION_STATEMENTS:
        raise MigrationError(
            f"Migration {migration.label} must not manage transactions"
        )
    if re.match(r"(?is)^PRAGMA\s+(?:main\.)?user_version\b", normalized):
        raise MigrationError(
            f"Migration {migration.label} must not set user_version"
        )


def _strip_comments(statement: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", statement, flags=re.DOTALL)
    return re.sub(r"--[^\n]*(?:\n|$)", "", without_blocks).strip()
