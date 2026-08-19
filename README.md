# Sal Resources Manager

## Setup

Create the local configuration:

```bash
cp config/config_template.ini config/config.ini
```

Set the Telegram `TOKEN`, Google Sheets report key, and the server's public
IPv4 address:

```ini
WEBHOOK_URL = https://203.0.113.10:8443/telegram/
GAME_DATA_GTABLE_KEY = <report spreadsheet id>
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

Prometheus is available at `http://127.0.0.1:9090`. It scrapes the bot,
Grafana, its own runtime, and a private `node_exporter` endpoint. The exporter
reads Linux host metrics through read-only mounts and its port `9100` is not
published on the host.

Grafana is published on all host interfaces at `http://<server-ip>:3000`.
Prometheus is provisioned as its default datasource. Grafana loads two
dashboards automatically:

- `Sal Resource Manager — Пользователи` for webhook traffic, bot actions,
  player resources, reminders, and reports;
- `Sal Resource Manager — Система` for readiness, uptime, process CPU and
  memory relative to the Compose limits, Prometheus/Grafana resource usage,
  and server CPU, load average, and available memory.

Set the initial
administrator credentials in `config/config.ini`:

```ini
[security]
admin_user = admin
admin_password = replace-with-a-strong-password
```

Grafana reads these values only when it creates the administrator in an empty
`grafana-data` volume. For an existing installation, change the password in
Grafana instead.

Application metrics include:

- `srm_ready`;
- webhook traffic: `srm_requests_total`, `srm_request_duration_seconds`,
  `srm_request_size_bytes`, `srm_requests_in_progress`, and
  `srm_last_request_timestamp_seconds`;
- bot processing: `srm_events_total`, `srm_event_errors_total`,
  `srm_event_duration_seconds`, `srm_events_in_progress`, and
  `srm_last_event_timestamp_seconds`;
- matched bot actions: `srm_event_outcomes_total`, `srm_handler_calls_total`,
  `srm_handler_duration_seconds`, and `srm_handlers_in_progress`;
- access decisions: `srm_access_checks_total`;
- reminders: `srm_reminders_total`, `srm_reminder_runs_total`, and
  `srm_next_reminder_timestamp_seconds`;
- report exports: `srm_reports_total` and `srm_report_duration_seconds`;
- player data changes: `srm_resource_updates_total` and
  `srm_last_resource_update_timestamp_seconds`;
- war score usage: `srm_score_calculations_total` and
  `srm_score_calculation_duration_seconds`;
- players and accounts: `srm_users`, `srm_accounts`, and
  `srm_users_by_account_count`.

Request metrics are recorded at the HTTP webhook layer and include every
Telegram request, its method, and response status. Event outcome metrics
separate authorized updates that matched a registered bot handler from group
messages that reached the webhook but were ignored. Handler metrics use the
finite registered function name as the action label. Slow calls can be selected
in Grafana using a configurable histogram threshold. Every completed handler
call is logged at `INFO` with its action, result, duration, user/chat/update
identifiers, and exception type.

The Python client also exposes its standard process, runtime, and garbage
collector metrics.

## Data

SQLite data is stored in `data/`. See [`db/README.md`](db/README.md)
for migrations. Google Sheets is used only for on-demand report exports.
