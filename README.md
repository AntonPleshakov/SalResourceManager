# Sal Resources Manager

## Setup

1. Install Docker with Docker Compose.
2. Create the configuration:

   ```bash
   cp config/config_template.ini config/config.ini
   ```

3. Fill in `config/config.ini` and place the Google service account key in the
   project root as `gapi_service_file.json`.

The persistent `data/` directory contains the SQLite mirror. When running
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

## SQLite migration stage 1

Before Telegram polling starts, the application creates or validates
`data/sal_resources.db`, imports all five Google-backed tables in one
transaction, and verifies the stored rows. It then enables dual-write with
Google first and SQLite second. Reads continue to use the data loaded from
Google Sheets. If validation or import fails, the bot does not start. A later
startup safely replaces the SQLite contents with a fresh Google snapshot
before enabling writes again.

SQLite schema changes use one global sequence of immutable migrations. See
`db/sqlite/README.md` for the migration rules.
