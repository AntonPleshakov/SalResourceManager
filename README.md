# Sal Resources Manager

## Setup

1. Install Docker with Docker Compose.
2. Copy the configuration template:

   ```bash
   cp config/config_template.ini config/config.ini
   ```

3. Fill in `config/config.ini`.
4. Place the Google service account key in the project root as
   `gapi_service_file.json`.

## Run

```bash
docker compose up --build -d
```

The `Release` configuration is used by default. To run in `Debug` mode:

```bash
MODE=Debug docker compose up --build -d
```

View logs:

```bash
docker compose logs -f bot
```

Stop the bot:

```bash
docker compose down
```
