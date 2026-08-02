# Sal Resources Manager

## Setup

1. Install Docker with Docker Compose.
2. Create the configuration:

   ```bash
   cp config/config_template.ini config/config.ini
   ```

3. Fill in `config/config.ini` and place the Google service account key in the
   project root as `gapi_service_file.json`.

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
