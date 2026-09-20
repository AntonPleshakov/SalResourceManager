import io
import sqlite3
import tarfile
from pathlib import Path

import pytest

from infra.configure_server.settings import Settings as ConfigureSettings
from infra.migrate_server import migration
from infra.migrate_server.settings import (
    Connection,
    MigrationSettings,
    resolve_settings,
)


def make_settings(tmp_path, **overrides):
    source = Connection("old-server", None, None)
    destination = Connection("new-server", None, None)
    deployment = ConfigureSettings(
        target=destination.target,
        config_file=tmp_path / "config.ini",
        google_oauth_token_file=tmp_path / "google_oauth_token.json",
        identity_file=None,
        port=None,
        ghcr_username=None,
        ghcr_token=None,
    )
    values = {
        "source": source,
        "destination": destination,
        "deployment": deployment,
        "backup_file": tmp_path / "backup.db",
        "overwrite_destination": False,
        "assume_yes": True,
    }
    values.update(overrides)
    return MigrationSettings(**values)


def test_resolve_settings_supports_separate_connections(tmp_path):
    old_identity = tmp_path / "old-key"
    new_identity = tmp_path / "new-key"

    settings = resolve_settings(
        [
            "old-server",
            "new-server",
            "--source-identity",
            str(old_identity),
            "--source-port",
            "2201",
            "--identity",
            str(new_identity),
            "--port",
            "2202",
            "--yes",
        ],
        {},
    )

    assert settings.source == Connection("old-server", old_identity.resolve(), 2201)
    assert settings.destination == Connection(
        "new-server", new_identity.resolve(), 2202
    )
    assert settings.deployment.target == "new-server"
    assert settings.assume_yes is True


def test_identical_hosts_are_rejected():
    with pytest.raises(Exception, match="must differ"):
        resolve_settings(["server", "server"], {})


def test_validate_database_accepts_consistent_sqlite_file(tmp_path):
    database = tmp_path / "database.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE example (value TEXT)")

    migration.validate_database(database)


def test_validate_database_rejects_invalid_file(tmp_path):
    database = tmp_path / "database.db"
    database.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        migration.validate_database(database)


@pytest.mark.parametrize(
    "host",
    ["8.8.8.8", "bot.example.com"],
)
def test_webhook_validation_accepts_ipv4_and_dns_names(tmp_path, host):
    config = tmp_path / "config.ini"
    config.write_text(
        f"[DEFAULT]\nWEBHOOK_URL=https://{host}:8443/telegram/\n[Release]\n",
        encoding="utf-8",
    )

    migration._validate_webhook_url(config)


def test_validate_volume_backup_accepts_safe_archive(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("metrics", encoding="utf-8")
    archive = tmp_path / "volume.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname="data/source.txt")

    migration.validate_volume_backup(archive)


@pytest.mark.parametrize("overwrite", [False, True])
def test_upload_volume_only_clears_existing_data_when_requested(
    tmp_path,
    monkeypatch,
    overwrite,
):
    archive = tmp_path / "volume.tar.gz"
    archive.write_bytes(b"archive")
    remote_scripts = []
    monkeypatch.setattr(migration, "run_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        migration,
        "run_remote",
        lambda connection, script, **kwargs: remote_scripts.append(script),
    )

    migration.upload_volume(
        Connection("new-server", None, None),
        migration.VOLUME_BACKUPS[0],
        archive,
        overwrite,
    )

    assert ("rm -rf /target" in remote_scripts[0]) is overwrite
    assert "sal-resource-manager_prometheus-data" in remote_scripts[0]


def test_optional_victorialogs_volume_is_skipped_when_absent(monkeypatch):
    inspected = []

    def inspect(connection, script, **kwargs):
        inspected.append(script)
        if migration.VICTORIALOGS_VOLUME in script:
            raise migration.subprocess.CalledProcessError(1, script)

    monkeypatch.setattr(migration, "run_remote", inspect)

    backups = migration.available_volume_backups(
        Connection("old-server", None, None)
    )

    assert [backup.label for backup in backups] == ["prometheus", "grafana"]
    assert any(migration.VICTORIALOGS_VOLUME in script for script in inspected)


def test_migration_rolls_back_when_configuration_fails(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    events = []

    monkeypatch.setattr(migration, "preflight", lambda _: events.append("preflight"))
    monkeypatch.setattr(
        migration,
        "available_volume_backups",
        lambda connection: list(migration.VOLUME_BACKUPS[:2]),
    )
    monkeypatch.setattr(
        migration,
        "stop_source_services",
        lambda connection, quiet=False: events.append(f"stop:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "start_source_services",
        lambda connection, quiet=False: events.append(f"start:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "stop_destination_services",
        lambda connection, quiet=False: events.append(f"stop:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "download_database",
        lambda connection, path: events.append("download"),
    )
    monkeypatch.setattr(
        migration,
        "validate_database",
        lambda path: events.append("validate"),
    )
    monkeypatch.setattr(
        migration,
        "upload_database",
        lambda connection, path: events.append("upload"),
    )
    monkeypatch.setattr(migration, "download_volume", lambda *args: None)
    monkeypatch.setattr(migration, "validate_volume_backup", lambda *args: None)
    monkeypatch.setattr(migration, "upload_volume", lambda *args: None)

    def fail_configuration(settings):
        if settings.prepare_only:
            events.append("prepare")
            return
        events.append("configure")
        raise RuntimeError("deployment failed")

    monkeypatch.setattr(migration, "configure_server", fail_configuration)

    with pytest.raises(RuntimeError, match="deployment failed"):
        migration.migrate(settings, io.StringIO(""))

    assert events == [
        "preflight",
        "prepare",
        "stop:old-server",
        "download",
        "validate",
        "upload",
        "configure",
        "stop:new-server",
        "start:old-server",
    ]


def test_migration_leaves_old_bot_stopped_after_success(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    events = []

    monkeypatch.setattr(migration, "preflight", lambda _: None)
    monkeypatch.setattr(
        migration,
        "available_volume_backups",
        lambda connection: list(migration.VOLUME_BACKUPS[:2]),
    )
    monkeypatch.setattr(
        migration,
        "stop_source_services",
        lambda connection, quiet=False: events.append(f"stop:{connection.target}"),
    )
    monkeypatch.setattr(migration, "download_database", lambda *args: None)
    monkeypatch.setattr(migration, "validate_database", lambda *args: None)
    monkeypatch.setattr(migration, "upload_database", lambda *args: None)
    monkeypatch.setattr(migration, "download_volume", lambda *args: None)
    monkeypatch.setattr(migration, "validate_volume_backup", lambda *args: None)
    monkeypatch.setattr(migration, "upload_volume", lambda *args: None)
    monkeypatch.setattr(
        migration,
        "configure_server",
        lambda settings: events.append(
            "prepare" if settings.prepare_only else "configure"
        ),
    )

    migration.migrate(settings, io.StringIO(""))

    assert events == ["prepare", "stop:old-server", "configure"]


def test_migration_rolls_back_when_interrupted_after_stop(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    events = []

    monkeypatch.setattr(migration, "preflight", lambda _: None)
    monkeypatch.setattr(
        migration,
        "available_volume_backups",
        lambda connection: list(migration.VOLUME_BACKUPS[:2]),
    )
    monkeypatch.setattr(migration, "configure_server", lambda settings: None)
    monkeypatch.setattr(
        migration,
        "stop_source_services",
        lambda connection, quiet=False: events.append(f"stop:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "start_source_services",
        lambda connection, quiet=False: events.append(f"start:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "stop_destination_services",
        lambda connection, quiet=False: events.append(f"stop:{connection.target}"),
    )
    monkeypatch.setattr(
        migration,
        "download_database",
        lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        migration.migrate(settings, io.StringIO(""))

    assert events == [
        "stop:old-server",
        "stop:new-server",
        "start:old-server",
    ]
