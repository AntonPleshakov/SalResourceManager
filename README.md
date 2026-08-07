# Sal Resources Manager

## Setup

1. Install Docker with Docker Compose.
2. Create the configuration:

   ```bash
   cp config/config_template.ini config/config.ini
   ```

3. Fill in `config/config.ini` and place the Google service account key in the
   project root as `gapi_service_file.json`.

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

## SQLite migration stage 2

Before Telegram polling starts, the application opens or creates
`data/sal_resources.db` and applies all pending migrations. Application reads
then use SQLite. Writes go to Google first and SQLite second. Startup does not
validate the resulting schema or compare SQLite data with Google Sheets.

The database must already contain a successful stage 1 import before this
version is deployed. An empty SQLite file receives the schema migrations but
does not receive existing Google data automatically.

SQLite schema changes use one global sequence of immutable migrations. See
`db/sqlite/README.md` for the migration rules.
