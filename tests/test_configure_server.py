from pathlib import Path

import pytest

from infra.configure_server import settings as configure_settings
from infra.configure_server import transport


def make_settings(**overrides):
    values = {
        "target": "sal-production",
        "config_file": Path("config.ini"),
        "google_credentials_file": Path("credentials.json"),
        "identity_file": None,
        "port": None,
        "ghcr_username": None,
        "ghcr_token": None,
    }
    values.update(overrides)
    return configure_settings.Settings(**values)


def test_ssh_alias_does_not_add_connection_overrides():
    settings = make_settings()

    assert transport.ssh_command(settings, "true") == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "sal-production",
        "true",
    ]


def test_explicit_port_uses_correct_ssh_and_scp_flags(tmp_path):
    identity = tmp_path / "id_ed25519"
    settings = make_settings(identity_file=identity, port=2222)

    assert transport.ssh_options(settings)[-4:] == [
        "-i",
        str(identity),
        "-p",
        "2222",
    ]
    assert transport.scp_options(settings)[-4:] == [
        "-i",
        str(identity),
        "-P",
        "2222",
    ]


def test_environment_provides_target_and_connection_settings(tmp_path):
    identity = tmp_path / "id_ed25519"
    settings = configure_settings.resolve_settings(
        [],
        {
            "SSH_TARGET": "sal-staging",
            "SSH_IDENTITY_FILE": str(identity),
            "SSH_PORT": "2200",
        },
    )

    assert settings.target == "sal-staging"
    assert settings.identity_file == identity.resolve()
    assert settings.port == 2200


@pytest.mark.parametrize("port", ["zero", "0", "65536"])
def test_invalid_port_is_rejected(port):
    with pytest.raises(configure_settings.ConfigureError, match="SSH port"):
        configure_settings.resolve_settings(["server", "-p", port], {})


def test_partial_registry_credentials_are_rejected():
    with pytest.raises(
        configure_settings.ConfigureError,
        match="GHCR_USERNAME and GHCR_TOKEN",
    ):
        configure_settings.resolve_settings(
            ["server"],
            {"GHCR_USERNAME": "deploy"},
        )


def test_remote_script_is_uploaded_executed_and_cleaned_up(monkeypatch):
    settings = make_settings()
    calls = []

    monkeypatch.setattr(transport, "require_local_prerequisites", lambda _: None)
    monkeypatch.setattr(
        transport.uuid,
        "uuid4",
        lambda: type("Uuid", (), {"hex": "fixed"})(),
    )

    def record(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(transport, "run_command", record)

    transport.configure_server(settings)

    remote_dir = "/tmp/sal-resource-manager-configure-fixed"
    assert calls[0][0][-1] == f"install -d -m 0700 {remote_dir}"
    assert any(
        call[0][0] == "scp"
        and call[0][-2] == str(configure_settings.REMOTE_SCRIPT_FILE)
        and call[0][-1].endswith(f":{remote_dir}/configure-remote.sh")
        for call in calls
    )
    assert any(
        call[0][0] == "scp"
        and call[0][-2] == str(configure_settings.CERTIFICATE_SCRIPT_FILE)
        and call[0][-1].endswith(
            f":{remote_dir}/generate-webhook-certificate.sh"
        )
        for call in calls
    )
    assert any(
        call[0][0] == "scp"
        and call[0][-2] == str(configure_settings.PROMETHEUS_CONFIG_FILE)
        and call[0][-1].endswith(f":{remote_dir}/prometheus.yml")
        for call in calls
    )
    assert f"bash {remote_dir}/configure-remote.sh {remote_dir}" in calls[-2][0][-1]
    assert calls[-2][1] == {}
    assert calls[-1][1] == {"quiet": True}
    assert calls[-1][0][-1].startswith("rm -f ")
