# Sal Resources Manager

## Setup

1. Install Docker with Docker Compose.
2. Create the configuration:

   ```bash
   cp config/config_template.ini config/config.ini
   ```

3. Fill in `config/config.ini` and place the Google service account key used
   for administrative report exports in the project root as
   `gapi_service_file.json`.

The persistent `data/` directory contains the SQLite database. When running
Docker on Linux, make sure it is writable by UID `10001` used in the container.

For remote host setup and reconciliation, see `infra/README.md`.

## Run

```bash
docker compose pull
docker compose up -d
```

View logs:

```bash
docker compose logs -f bot
```

Stop the bot:

```bash
docker compose down
```

## SQLite storage

Before Telegram polling starts, the application opens or creates
`data/sal_resources.db` and applies all pending migrations. All application
reads and writes use SQLite.

SQLite schema changes use one global sequence of immutable migrations. See
`db/sqlite/README.md` for the migration rules.

Google Sheets is not an application database. The administrative "Game data"
report exports an on-demand snapshot from SQLite through the retained
`db/gapi` utility package.

Configure its destination with `GAME_DATA_GTABLE_KEY` and
`USER_DATA_PAGE_NAME`. The service account from `GSERVICE_FILE` must have edit
access to that spreadsheet.
