# Optional Google API utilities

The application database does not depend on this package. The administrative
game-data report uses `GSheetsManager` only to export an on-demand SQLite
snapshot. Google Drive utilities remain optional and are not used at runtime.

The report and integration tests require a Google service account and the
`GSERVICE_EMAIL`, `GSERVICE_FILE`, `GDRIVE_FOLDER_PATH`, `TEST_GTABLE_KEY`, and
`TEST_PAGE_NAME` settings from `config/config_template.ini`.

The administrative report additionally uses `GAME_DATA_GTABLE_KEY` and
`USER_DATA_PAGE_NAME`.
