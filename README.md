# Sal Resources Manager

## Setup

Create the local configuration:

```bash
cp config/config_template.ini config/config.ini
```

Set the Telegram `TOKEN`, report settings, and the server's public IPv4 address:

```ini
WEBHOOK_URL = https://203.0.113.10:8443/telegram/
```

Place the Google service-account key at `gapi_service_file.json`. For remote
server provisioning, webhook certificates, and deployment, see
[`infra/README.md`](infra/README.md).

## Run

```bash
docker compose pull
docker compose up -d
docker compose logs -f bot
```

## Data

SQLite data is stored in `data/`. See [`db/README.md`](db/README.md)
for migrations. Google Sheets is used only for on-demand report exports.
