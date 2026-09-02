# Sal Resources Manager

## Setup

```bash
cp config/config_template.ini config/config.ini
```

Set `TOKEN`, `WEBHOOK_URL`, `GAME_DATA_GFOLDER_KEY`, and Grafana credentials in
`config/config.ini`. The Google Drive folder must be private and accessible only
to the service account, which must be able to create files and approve access
requests. Report viewers request an individual clan file and receive the
`reader` role.
Enable the Drive API and place the service-account key at
`gapi_service_file.json`. See
[`infra/README.md`](infra/README.md) for server deployment.

## Run

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
