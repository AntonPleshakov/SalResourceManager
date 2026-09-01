"""Facade for game-account, preference, and resource storage."""

from db.repository import DatabaseRepository
from db.user_data_storage import (
    AccountCommands,
    UserDataQueries,
    UserDataValues,
    UserPreferences,
)


class UserDataDB(
    DatabaseRepository,
    UserDataQueries,
    UserPreferences,
    AccountCommands,
    UserDataValues,
):
    pass


__all__ = ["UserDataDB"]
