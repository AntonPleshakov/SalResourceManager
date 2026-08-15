import configparser
import json
from pathlib import Path


DASHBOARD_FILE = (
    Path(__file__).parents[1]
    / "config"
    / "grafana"
    / "sal-resource-manager.json"
)
PROJECT_DIR = Path(__file__).parents[1]


def test_grafana_dashboard_uses_provisioned_prometheus_metrics() -> None:
    dashboard = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    panels = dashboard["panels"]
    queries = "\n".join(
        target["expr"]
        for panel in panels
        for target in panel.get("targets", [])
    )

    assert dashboard["uid"] == "sal-resource-manager"
    assert len({panel["id"] for panel in panels}) == len(panels)
    assert all(
        panel.get("datasource", {}).get("uid") == "prometheus"
        for panel in panels
        if panel["type"] != "row"
    )
    for metric in (
        "srm_ready",
        "srm_users",
        "srm_accounts",
        "srm_users_by_account_count",
        "srm_requests_total",
        "srm_request_duration_seconds_bucket",
        "srm_request_size_bytes_bucket",
        "srm_events_total",
        "srm_event_errors_total",
        "srm_resource_updates_total",
        "srm_score_calculations_total",
        "srm_access_checks_total",
        "srm_reminders_total",
        "srm_reports_total",
    ):
        assert metric in queries


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
