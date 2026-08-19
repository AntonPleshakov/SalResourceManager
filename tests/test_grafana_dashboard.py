import configparser
import json
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
        "srm_reminders_total",
        "srm_reminder_runs_total",
        "srm_next_reminder_timestamp_seconds",
        "srm_reports_total",
        "srm_report_duration_seconds_bucket",
    ):
        assert metric in queries
    assert "reqps" not in json.dumps(dashboard)
    assert "* 60" in queries
    assert dashboard["templating"]["list"][0]["name"] == "slow_threshold"
    assert 'le="$slow_threshold"' in queries
    assert "by (le, handler)" in queries


def test_system_dashboard_uses_process_limits_and_runtime_metrics() -> None:
    dashboard = json.loads(SYSTEM_DASHBOARD_FILE.read_text(encoding="utf-8"))
    queries = _queries(dashboard)

    assert dashboard["uid"] == "sal-resource-manager-system"
    _assert_dashboard_structure(dashboard)
    for metric in (
        "process_resident_memory_bytes",
        "process_cpu_seconds_total",
        "process_start_time_seconds",
        "process_open_fds",
        "scrape_duration_seconds",
        "python_gc_collections_total",
        "node_memory_MemAvailable_bytes",
        "node_memory_MemTotal_bytes",
        "node_cpu_seconds_total",
        "node_load1",
        "node_load5",
        "node_load15",
    ):
        assert metric in queries
    assert "268435456" in queries
    assert "/ 0.5" in queries
    assert 'job=~"prometheus|grafana"' in queries


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
    assert "pull bot node-exporter prometheus grafana" in (
        PROJECT_DIR / "infra/configure_server/remote.sh"
    ).read_text(encoding="utf-8")


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


def test_grafana_port_is_published_on_all_host_interfaces() -> None:
    compose = (PROJECT_DIR / "compose.yaml").read_text(encoding="utf-8")

    assert '- "3000:3000"' in compose
    assert "127.0.0.1:3000:3000" not in compose


def test_server_configuration_allows_grafana_through_ufw() -> None:
    remote_script = (
        PROJECT_DIR / "infra" / "configure_server" / "remote.sh"
    ).read_text(encoding="utf-8")

    assert "ufw allow 3000/tcp" in remote_script
