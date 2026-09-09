# Sal Resources Manager

## Setup

```bash
cp config/config_template.ini config/config.ini
```

Set `TOKEN`, `WEBHOOK_URL`, `GAME_DATA_GFOLDER_KEY`, and Grafana credentials in
`config/config.ini`. `GAME_DATA_GFOLDER_KEY` must identify a private folder
owned by the Google account used for report export. Enable the Drive and Sheets
APIs, create a [Desktop OAuth client](https://console.cloud.google.com/auth/clients),
place its JSON at `config/google_oauth_client.json`, and run the authorization
command from [`infra/README.md`](infra/README.md) once to create
`config/google_oauth_token.json`. See the same document for server deployment.

## Run

Local debug mode uses Telegram long polling, so it does not require a public
webhook URL or TLS certificates. For clans present in the local database, chat
and membership lookups are simulated from local clan and administrator data:

```powershell
$env:MODE = "Debug"
python main.py
```

Production runs with webhooks through Docker:

```bash
docker compose pull
docker compose up -d
docker compose logs -f bot
```

Grafana: `http://<server-ip>:3000`. Prometheus:
`http://127.0.0.1:9090`. SQLite data is stored in `data/`; migration rules are
in [`db/README.md`](db/README.md).

## Clans

Each Telegram group is a clan. Users and administrators may belong to several
clans; accounts and administrative actions belong to one selected clan.

Register a clan with `/register_group` inside its Telegram group or use the
admin panel. The bot must be an administrator so Telegram reliably allows it
to verify users' membership in the group.
