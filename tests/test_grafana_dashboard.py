import configparser
import json
import re
from pathlib import Path


DASHBOARD_FILE = (
    Path(__file__).parents[1]
    / "config"
    / "grafana"
    / "sal-resource-manager.json"
)
SYSTEM_DASHBOARD_FILE = (
    Path(__file__).parents[1]
    / "config"
    / "grafana"
    / "sal-resource-manager-system.json"
)
LOGS_DASHBOARD_FILE = (
    Path(__file__).parents[1]
    / "config"
    / "grafana"
    / "sal-resource-manager-logs.json"
)
PROJECT_DIR = Path(__file__).parents[1]


def _queries(dashboard: dict) -> str:
    return "\n".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )


def _assert_dashboard_structure(dashboard: dict) -> None:
    panels = dashboard["panels"]
    assert len({panel["id"] for panel in panels}) == len(panels)
    assert all(
        panel.get("datasource", {}).get("uid") == "prometheus"
        for panel in panels
        if panel["type"] != "row"
    )
    assert all(
        "$__range" not in target["expr"] or not target.get("range", True)
        for panel in panels
        for target in panel.get("targets", [])
    )


def test_user_dashboard_uses_actionable_prometheus_metrics() -> None:
    dashboard = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    queries = _queries(dashboard)

    assert dashboard["uid"] == "sal-resource-manager"
    _assert_dashboard_structure(dashboard)
    for metric in (
        "srm_ready",
        "srm_users",
        "srm_accounts",
        "srm_clans",
        "srm_clan_users",
        "srm_clan_accounts",
        "srm_users_by_account_count",
        "srm_requests_total",
        "srm_request_duration_seconds_bucket",
        "srm_event_outcomes_total",
        "srm_handler_calls_total",
        "srm_handler_duration_seconds_bucket",
        "srm_resource_updates_total",
        "srm_last_resource_update_timestamp_seconds",
        "srm_score_calculations_total",
        "srm_access_checks_total",
        "srm_reports_total",
        "srm_report_duration_seconds_bucket",
    ):
        assert metric in queries
    for metric in (
        "srm_reminders_total",
        "srm_reminder_runs_total",
        "srm_next_reminder_timestamp_seconds",
    ):
        assert metric not in queries
    assert "reqps" not in json.dumps(dashboard)
    assert "* 60" in queries
    assert dashboard["templating"]["list"][0]["name"] == "slow_threshold"
    assert 'le="$slow_threshold"' in queries
    assert "by (le, handler)" in queries
    assert any(panel["title"] == "Кланы" for panel in dashboard["panels"])
    assert any(
        panel["title"] == "Пользователи по кланам"
        for panel in dashboard["panels"]
    )
    assert any(
        panel["title"] == "Игровые аккаунты по кланам"
        for panel in dashboard["panels"]
    )


def test_system_dashboard_uses_process_limits_and_server_metrics() -> None:
    dashboard = json.loads(SYSTEM_DASHBOARD_FILE.read_text(encoding="utf-8"))
    queries = _queries(dashboard)

    assert dashboard["uid"] == "sal-resource-manager-system"
    _assert_dashboard_structure(dashboard)
    panel_y_positions = [
        panel["gridPos"]["y"] for panel in dashboard["panels"]
    ]
    assert panel_y_positions == sorted(panel_y_positions)
    for metric in (
        "process_resident_memory_bytes",
        "process_cpu_seconds_total",
        "process_start_time_seconds",
        "node_memory_MemAvailable_bytes",
        "node_memory_MemTotal_bytes",
        "node_filesystem_avail_bytes",
        "node_filesystem_size_bytes",
        "node_cpu_seconds_total",
        "node_load1",
        "node_load5",
        "node_load15",
    ):
        assert metric in queries
    assert "268435456" in queries
    assert "vector(0.5)" in queries

    memory_panels = [
        panel
        for panel in dashboard["panels"]
        if "process_resident_memory_bytes"
        in "\n".join(target["expr"] for target in panel.get("targets", []))
    ]
    cpu_panels = [
        panel
        for panel in dashboard["panels"]
        if "process_cpu_seconds_total"
        in "\n".join(target["expr"] for target in panel.get("targets", []))
    ]
    assert [panel["title"] for panel in memory_panels] == [
        "Память: бот, Prometheus и Grafana"
    ]
    assert [panel["title"] for panel in cpu_panels] == [
        "CPU: бот, Prometheus и Grafana"
    ]
    assert any(
        panel["title"] == "NVMe: хранилище сервера"
        for panel in dashboard["panels"]
    )

    def panel_y(title: str) -> int:
        matching_panels = [
            panel for panel in dashboard["panels"] if panel["title"] == title
        ]
        assert len(matching_panels) == 1
        return matching_panels[0]["gridPos"]["y"]

    assert panel_y("Память: бот, Prometheus и Grafana") == 5
    assert panel_y("CPU: бот, Prometheus и Grafana") == 5
    assert panel_y("NVMe: хранилище сервера") == 14
    assert panel_y("Uptime процесса") > panel_y("NVMe: хранилище сервера")


def test_prometheus_scrapes_grafana_and_private_node_exporter() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    prometheus = (PROJECT_DIR / "config/prometheus.yml").read_text(
        encoding="utf-8"
    )

    assert "quay.io/prometheus/node-exporter:v1.11.1" in compose
    assert "- /:/host:ro,rslave" in compose
    assert "node-exporter:9100" in prometheus
    assert "grafana:3000" in prometheus
    assert "9100:9100" not in compose
    assert "node-exporter:9100:9100" not in compose
    remote_script = (
        PROJECT_DIR / "infra/configure_server/remote.sh"
    ).read_text(encoding="utf-8")
    assert "victorialogs vector" in remote_script


def test_grafana_uses_a_separate_restricted_config() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    remote_script = (
        PROJECT_DIR / "infra" / "configure_server" / "remote.sh"
    ).read_text(encoding="utf-8")
    template = configparser.ConfigParser()
    template.read(PROJECT_DIR / "config" / "config_template.ini", encoding="utf-8")

    assert "GF_SECURITY_ADMIN_USER" not in compose
    assert "GF_SECURITY_ADMIN_PASSWORD" not in compose
    assert "./config/grafana/grafana.ini:/etc/grafana/grafana.ini:ro" in compose
    assert "${CONFIG_FILE:-./config/config.ini}:/etc/grafana/grafana.ini" not in compose
    assert "sal-resource-manager-system.json:/etc/grafana/dashboards/" in compose
    assert 'GRAFANA_UID="472"' in remote_script
    assert '"$GRAFANA_UID" "$GRAFANA_GID" 0400 true' in remote_script
    assert "generate_grafana_config" in remote_script
    assert template.has_option("security", "admin_user")
    assert template.has_option("security", "admin_password")


def test_caddy_is_the_only_public_entrypoint() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    bot_service = compose.split("  bot:", 1)[1].split("  node-exporter:", 1)[0]

    assert '- "80:80"' in compose
    assert '- "8443:8443"' in compose
    assert '- "443:443"' not in compose
    assert "ports:" not in bot_service
    assert '- "3000:3000"' not in compose
    assert "caddy-data:/data" in compose
    assert "caddy-config:/config" in compose
    assert "./config/oauth:/srv/oauth:ro" in compose
    assert "CADDY_OAUTH_HOST" in compose


def test_caddy_waits_until_grafana_is_ready() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    grafana_service = compose.split("  grafana:", 1)[1].split("  caddy:", 1)[0]
    caddy_service = compose.split("  caddy:", 1)[1].split("  victorialogs:", 1)[0]

    assert 'http://localhost:3000/api/health' in grafana_service
    assert 'test: ["CMD", "curl", "-fsS"' in grafana_service
    assert "grafana:\n        condition: service_healthy" in caddy_service
    assert "restart: true" in caddy_service


def test_server_configuration_only_allows_caddy_through_ufw() -> None:
    remote_script = (
        PROJECT_DIR / "infra" / "configure_server" / "remote.sh"
    ).read_text(encoding="utf-8")

    assert "ufw allow 80/tcp" in remote_script
    assert "ufw allow 8443/tcp" in remote_script
    assert "ufw allow 443/tcp" not in remote_script
    assert "ufw --force delete allow 3000/tcp" in remote_script


def test_victorialogs_is_bounded_and_available_in_grafana() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    vector = (PROJECT_DIR / "config/vector.yaml").read_text(encoding="utf-8")
    datasources = (
        PROJECT_DIR / "config/grafana/datasources.yml"
    ).read_text(encoding="utf-8")

    assert "amir20/dozzle" not in compose
    assert "victoriametrics/victoria-logs:v1.52.0" in compose
    assert "-retentionPeriod=7d" in compose
    assert "-retention.maxDiskSpaceUsageBytes=1GiB" in compose
    assert "victoriametrics-logs-datasource@0.32.0" in compose
    assert "- /var/run/docker.sock:/var/run/docker.sock:ro" in compose
    assert "type: docker_logs" in vector
    assert "when_full: drop_newest" in vector
    assert "type: victoriametrics-logs-datasource" in datasources


def test_logs_dashboard_uses_victorialogs_and_is_provisioned() -> None:
    dashboard = json.loads(LOGS_DASHBOARD_FILE.read_text(encoding="utf-8"))
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")
    queries = _queries(dashboard)

    assert dashboard["uid"] == "sal-resource-manager-logs"
    assert [panel["title"] for panel in dashboard["panels"]] == ["Логи"]
    assert all(
        panel["datasource"]["uid"] == "victorialogs"
        for panel in dashboard["panels"]
    )
    assert "container_name" in queries
    assert "_msg" in queries
    assert [variable["name"] for variable in dashboard["templating"]["list"]] == [
        "container",
        "level",
        "search",
    ]
    assert "sal-resource-manager-logs.json:/etc/grafana/dashboards/" in compose


def test_logs_are_readable_without_losing_original_details() -> None:
    dashboard = json.loads(LOGS_DASHBOARD_FILE.read_text(encoding="utf-8"))
    panel = dashboard["panels"][0]
    target = panel["targets"][0]
    query = target["expr"]

    assert target["queryType"] == "instant"
    assert target["packJson"] is False
    assert panel["options"]["syntaxHighlighting"] is False
    assert panel["options"]["showLabels"] is False
    assert panel["options"]["enableLogDetails"] is True
    assert "copy _msg as original" in query
    assert query.index('${search:raw}') < query.index("copy _msg as original")
    assert "format '[<service>] <_msg>' as _msg" in query
    assert 'unpack_json if (_msg:~"^\\s*[{]") fields (level, msg, message)' in query
    assert 'unpack_logfmt if (_msg:~"^(logger|ts|time|timestamp|level)="' in query
    assert "format '<parsed_msg>' as _msg skip_empty_results" in query
    assert "format '<parsed_message>' as _msg skip_empty_results" in query
    assert "replace_regexp ('^sal-resource-manager-?', '') at service" in query
    assert "replace_regexp '^sal-resource-manager-?' with ''" not in query


def test_logs_dashboard_defaults_to_application_logs() -> None:
    dashboard = json.loads(LOGS_DASHBOARD_FILE.read_text(encoding="utf-8"))
    variable = next(
        item for item in dashboard["templating"]["list"]
        if item["name"] == "container"
    )

    assert variable["type"] == "custom"
    assert variable["current"] == {
        "selected": True,
        "text": "Приложение",
        "value": "^sal-resource-manager$",
    }
    assert any(
        option["text"] == "Все сервисы"
        and option["value"] == "^sal-resource-manager(?:-.*)?$"
        for option in variable["options"]
    )


def test_logs_default_filter_preserves_info_errors_and_unknown_levels() -> None:
    dashboard = json.loads(LOGS_DASHBOARD_FILE.read_text(encoding="utf-8"))
    variable = next(v for v in dashboard["templating"]["list"] if v["name"] == "level")
    value = variable["current"]["value"]
    assert value.startswith('NOT level:~"')
    pattern = value.removeprefix('NOT level:~"').removesuffix('"')
    for level in ("debug", "DEBUG", "trace", "TRACE"):
        assert re.search(pattern, level)
    for level in ("info", "INFO", "warning", "error", "critical", "unknown", "", "notice"):
        assert not re.search(pattern, level)
    assert any(option["value"] == "*" for option in variable["options"])
    assert "| filter ${level:raw}" in _queries(dashboard)


def test_logs_extract_plaintext_level_and_message_without_losing_tracebacks() -> None:
    dashboard = json.loads(LOGS_DASHBOARD_FILE.read_text(encoding="utf-8"))
    patterns = re.findall(r"extract_regexp '([^']+)'", _queries(dashboard))
    cases = [
        (
            "20/09 15:35:04 INFO SalResourcesManager handlers:12 | Updated 3 accounts",
            "INFO", "Updated 3 accounts",
        ),
        (
            "20/09 15:35:04 ERROR SalResourcesManager handlers:12 | Export failed\nTraceback:\n  ValueError: invalid input",
            "ERROR", "Export failed\nTraceback:\n  ValueError: invalid input",
        ),
        (
            "20/09 15:35:04 INFO SalResourcesManager handlers:12 | Received level=debug in payload",
            "INFO", "Received level=debug in payload",
        ),
        (
            "2026-09-20T15:35:04.749Z\tinfo\tVictoriaLogs/main.go:12\tstarted server",
            "info", "started server",
        ),
    ]
    for line, level, message in cases:
        matches = [match for pattern in patterns if (match := re.search(pattern, line))]
        assert len(matches) == 1
        assert matches[0]["parsed_level"] == level
        assert matches[0]["parsed_message"] == message
    for line in ("unstructured log", "Traceback (most recent call last):", "  ValueError: bad input"):
        assert not any(re.search(pattern, line) for pattern in patterns)


def test_prometheus_has_a_disk_size_limit() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")

    assert "--storage.tsdb.retention.time=15d" in compose
    assert "--storage.tsdb.retention.size=1GB" in compose


def test_oauth_branding_site_has_required_public_pages() -> None:
    oauth_dir = PROJECT_DIR / "config" / "oauth"
    homepage = (oauth_dir / "index.html").read_text(encoding="utf-8")
    privacy = (oauth_dir / "privacy" / "index.html").read_text(
        encoding="utf-8"
    )
    terms = (oauth_dir / "terms" / "index.html").read_text(encoding="utf-8")
    caddyfile = (PROJECT_DIR / "config" / "Caddyfile").read_text(
        encoding="utf-8"
    )

    assert 'href="/privacy/"' in homepage
    assert 'href="/terms/"' in homepage
    assert "Google Drive" in homepage
    assert "Google Sheets" in homepage
    assert "OAuth-токен" in privacy
    assert "не продаются" in privacy
    assert "Google Account" in terms
    assert "{$CADDY_OAUTH_HOST}:8443" in caddyfile
    assert "root * /srv/oauth" in caddyfile
