from resources.user_data import UserData


IDENTITY_COLUMNS = ("account_id", "user_id", "username", "tag")
USER_DATA_COLUMNS = tuple(
    column for column in UserData().params() if column not in IDENTITY_COLUMNS
)
USER_DATA_TEXT_COLUMNS = frozenset(
    column for column in USER_DATA_COLUMNS if column.endswith("_updated_on")
)
QUOTED_DATA_COLUMNS = ", ".join(
    f'"{column}"' for column in ("account_id", *USER_DATA_COLUMNS)
)
DATA_PLACEHOLDERS = ", ".join(["?"] * (len(USER_DATA_COLUMNS) + 1))
DATA_UPDATE_ASSIGNMENTS = ", ".join(
    f'"{column}" = excluded."{column}"' for column in USER_DATA_COLUMNS
)
SELECT_USER = (
    "SELECT ga.account_id, tu.user_id, tu.username, ga.tag, "
    + ", ".join(f'ud."{column}"' for column in USER_DATA_COLUMNS)
    + " FROM game_accounts ga "
    "JOIN telegram_users tu ON tu.user_id = ga.user_id "
    "JOIN user_data ud ON ud.account_id = ga.account_id "
)


def write_user(connection, user: UserData) -> None:
    row = [int(user.account_id.value)]
    for column in USER_DATA_COLUMNS:
        value = getattr(user, column).value
        row.append(str(value or "") if column in USER_DATA_TEXT_COLUMNS else int(value))
    connection.execute(
        f"INSERT INTO user_data ({QUOTED_DATA_COLUMNS}) "
        f"VALUES ({DATA_PLACEHOLDERS}) "
        f"ON CONFLICT(account_id) DO UPDATE SET {DATA_UPDATE_ASSIGNMENTS}",
        tuple(row),
    )
