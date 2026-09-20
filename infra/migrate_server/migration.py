"""Safe cutover orchestration for a server migration."""

from __future__ import annotations

import configparser
import ipaddress
import shlex
import sqlite3
import subprocess
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, TextIO
from urllib.parse import urlsplit

from infra.configure_server.settings import require_local_prerequisites
from infra.configure_server.transport import configure_server

from .settings import Connection, MigrationSettings


APP_DIR = "/opt/sal-resource-manager"
DATABASE_PATH = f"{APP_DIR}/data/sal_resources.db"
CONTAINER_NAME = "sal-resource-manager"
ARCHIVE_IMAGE = "docker.io/library/alpine:3.22"
VICTORIALOGS_VOLUME = "sal-resource-manager_victorialogs-data"


@dataclass(frozen=True)
class VolumeBackup:
    volume_name: str
    label: str
    required: bool


class MigrationError(RuntimeError):
    """An expected migration failure."""


VOLUME_BACKUPS = (
    VolumeBackup("sal-resource-manager_prometheus-data", "prometheus", True),
    VolumeBackup("sal-resource-manager_grafana-data", "grafana", True),
    VolumeBackup(VICTORIALOGS_VOLUME, "victorialogs", False),
)


def log(message: str) -> None:
    print(f"[migrate] {message}", flush=True)


def ssh_options(connection: Connection) -> list[str]:
    options = ["-o", "BatchMode=yes"]
    if connection.identity_file:
        options.extend(("-i", str(connection.identity_file)))
    if connection.port:
        options.extend(("-p", str(connection.port)))
    return options


def ssh_command(connection: Connection, remote_command: str) -> list[str]:
    return [
        "ssh",
        *ssh_options(connection),
        connection.target,
        remote_command,
    ]


def privileged_command(script: str) -> str:
    quoted_script = shlex.quote(script)
    return (
        'if [ "$(id -u)" -eq 0 ]; then '
        f"bash -c {quoted_script}; "
        "else "
        f"sudo -n bash -c {quoted_script}; "
        "fi"
    )


def run_command(
    command: Sequence[str],
    *,
    stdin: Optional[BinaryIO] = None,
    stdout: Optional[BinaryIO] = None,
    quiet: bool = False,
) -> None:
    subprocess.run(
        command,
        check=True,
        stdin=stdin,
        stdout=subprocess.DEVNULL if quiet else stdout,
        stderr=subprocess.DEVNULL if quiet else None,
    )


def run_remote(
    connection: Connection,
    script: str,
    *,
    stdin: Optional[BinaryIO] = None,
    stdout: Optional[BinaryIO] = None,
    quiet: bool = False,
) -> None:
    run_command(
        ssh_command(connection, privileged_command(script)),
        stdin=stdin,
        stdout=stdout,
        quiet=quiet,
    )


def _validate_webhook_url(config_file: Path) -> None:
    parser = configparser.ConfigParser()
    try:
        with config_file.open(encoding="utf-8") as file:
            parser.read_file(file)
        url = parser.get("Release", "WEBHOOK_URL")
        parsed = urlsplit(url.strip())
        port = parsed.port
    except (OSError, configparser.Error, ValueError) as error:
        raise MigrationError(
            f"Cannot read a valid Release WEBHOOK_URL from {config_file}: {error}"
        ) from error
    host = parsed.hostname or ""
    try:
        ipaddress.ip_address(host)
        is_ip_address = True
    except ValueError:
        is_ip_address = False
    labels = host.split(".")
    valid_hostname = (
        not is_ip_address
        and host.isascii()
        and len(host) <= 253
        and len(labels) >= 2
        and all(
            label
            and len(label) <= 63
            and label[0].isalnum()
            and label[-1].isalnum()
            and all(character.isalnum() or character == "-" for character in label)
            for label in labels
        )
    )
    if (
        parsed.scheme != "https"
        or port != 8443
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise MigrationError(
            "Release WEBHOOK_URL must use HTTPS on port 8443."
        )
    if not parsed.path.strip("/") or not valid_hostname:
        raise MigrationError(
            "Release WEBHOOK_URL must contain a path and a valid DNS name."
        )


def volume_backup_path(database_backup: Path, backup: VolumeBackup) -> Path:
    return database_backup.with_name(
        f"{database_backup.name}.{backup.label}.tar.gz"
    )


def _validate_local_settings(settings: MigrationSettings) -> None:
    require_local_prerequisites(settings.deployment)
    if settings.source.identity_file and not settings.source.identity_file.is_file():
        raise MigrationError(
            f"Source identity file does not exist: {settings.source.identity_file}"
        )
    if settings.backup_file.exists():
        raise MigrationError(
            f"Backup file already exists: {settings.backup_file}. "
            "Choose another path with --backup."
        )
    if not settings.backup_file.parent.is_dir():
        raise MigrationError(
            f"Backup directory does not exist: {settings.backup_file.parent}"
        )
    existing_volume_backups = [
        volume_backup_path(settings.backup_file, backup)
        for backup in VOLUME_BACKUPS
        if volume_backup_path(settings.backup_file, backup).exists()
    ]
    if existing_volume_backups:
        raise MigrationError(
            f"Volume backup file already exists: {existing_volume_backups[0]}. "
            "Choose another base path with --backup."
        )
    _validate_webhook_url(settings.deployment.config_file)


def _preflight_source(connection: Connection) -> None:
    volume_checks = " && ".join(
        f"docker volume inspect {shlex.quote(backup.volume_name)} >/dev/null"
        for backup in VOLUME_BACKUPS
        if backup.required
    )
    script = (
        "docker info >/dev/null && "
        f"test -s {shlex.quote(DATABASE_PATH)} && "
        f'test "$(docker inspect --format {{{{.State.Running}}}} '
        f'{shlex.quote(CONTAINER_NAME)} 2>/dev/null)" = true && '
        f"{volume_checks}"
    )
    run_remote(connection, script, quiet=True)


def _preflight_destination(
    connection: Connection,
    overwrite_destination: bool,
) -> None:
    database_check = "true" if overwrite_destination else f"test ! -e {DATABASE_PATH}"
    container_names = (
        "sal-resource-manager",
        "sal-resource-manager-prometheus",
        "sal-resource-manager-grafana",
        "sal-resource-manager-victorialogs",
        "sal-resource-manager-vector",
    )
    container_checks = " && ".join(
        f'if [ "$(docker inspect --format {{{{.State.Running}}}} '
        f'{shlex.quote(name)} 2>/dev/null || true)" = true ]; then exit 12; fi'
        for name in container_names
    )
    destination_volumes = [backup.volume_name for backup in VOLUME_BACKUPS]
    volume_check = "true" if overwrite_destination else " && ".join(
        f"! docker volume inspect {shlex.quote(volume)} >/dev/null 2>&1"
        for volume in destination_volumes
    )
    script = (
        "docker info >/dev/null && "
        f"{container_checks} && "
        f"{database_check} && {volume_check}"
    )
    run_remote(connection, script, quiet=True)


def preflight(settings: MigrationSettings) -> None:
    _validate_local_settings(settings)
    log("Checking the old server...")
    _preflight_source(settings.source)
    log("Checking the new server...")
    _preflight_destination(
        settings.destination,
        settings.overwrite_destination,
    )
    log("Pulling the temporary volume archive image on both servers...")
    archive_pull = f"docker pull {shlex.quote(ARCHIVE_IMAGE)} >/dev/null"
    run_remote(settings.source, archive_pull)
    run_remote(settings.destination, archive_pull)


def confirm_cutover(
    settings: MigrationSettings,
    input_stream: Optional[TextIO],
) -> None:
    if settings.assume_yes:
        return
    answer = input(
        f"Stop the bot on {settings.source.target} and move it to "
        f"{settings.destination.target}? Type 'migrate' to continue: "
    ) if input_stream is None else input_stream.readline().strip()
    if answer != "migrate":
        raise MigrationError("Migration cancelled.")


def available_volume_backups(connection: Connection) -> list[VolumeBackup]:
    available = []
    for backup in VOLUME_BACKUPS:
        try:
            run_remote(
                connection,
                f"docker volume inspect {shlex.quote(backup.volume_name)} >/dev/null",
                quiet=True,
            )
        except subprocess.CalledProcessError:
            if backup.required:
                raise
            continue
        available.append(backup)
    return available


def stop_source_services(connection: Connection, *, quiet: bool = False) -> None:
    run_remote(
        connection,
        f"cd {APP_DIR} && docker compose stop bot prometheus grafana && "
        "(docker stop dozzle >/dev/null 2>&1 || true)",
        quiet=quiet,
    )


def start_source_services(connection: Connection, *, quiet: bool = False) -> None:
    run_remote(
        connection,
        f"cd {APP_DIR} && docker compose start prometheus grafana bot && "
        "(docker start dozzle >/dev/null 2>&1 || true)",
        quiet=quiet,
    )


def stop_destination_services(
    connection: Connection,
    *,
    quiet: bool = False,
) -> None:
    run_remote(
        connection,
        f"cd {APP_DIR} && docker compose stop "
        "bot prometheus grafana victorialogs vector",
        quiet=quiet,
    )


def download_database(connection: Connection, backup_file: Path) -> None:
    wal_path = shlex.quote(f"{DATABASE_PATH}-wal")
    script = (
        f"if [ -s {wal_path} ]; then "
        "echo 'SQLite WAL still contains data after shutdown.' >&2; exit 20; fi; "
        f"cat {shlex.quote(DATABASE_PATH)}"
    )
    with backup_file.open("xb") as output:
        try:
            run_remote(connection, script, stdout=output)
        except BaseException:
            output.close()
            backup_file.unlink(missing_ok=True)
            raise


def validate_database(backup_file: Path) -> None:
    connection = sqlite3.connect(f"file:{backup_file.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result != ("ok",):
        raise MigrationError(f"SQLite integrity check failed: {result!r}")


def download_volume(
    connection: Connection,
    backup: VolumeBackup,
    backup_file: Path,
) -> None:
    script = (
        "docker run --rm --network none --read-only "
        f"--volume {shlex.quote(backup.volume_name)}:/source:ro "
        f"{shlex.quote(ARCHIVE_IMAGE)} tar -C /source -czf - ."
    )
    with backup_file.open("xb") as output:
        try:
            run_remote(connection, script, stdout=output)
        except BaseException:
            output.close()
            backup_file.unlink(missing_ok=True)
            raise


def validate_volume_backup(backup_file: Path) -> None:
    try:
        with tarfile.open(backup_file, "r:gz") as archive:
            members = archive.getmembers()
    except (OSError, tarfile.TarError) as error:
        raise MigrationError(
            f"Cannot read volume backup {backup_file}: {error}"
        ) from error
    if not members:
        raise MigrationError(f"Volume backup is empty: {backup_file}")
    for member in members:
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise MigrationError(
                f"Volume backup contains an unsafe path: {member.name}"
            )


def upload_database(connection: Connection, backup_file: Path) -> None:
    temporary_path = f"/tmp/sal-resources-migration-{backup_file.name}"
    quoted_temporary = shlex.quote(temporary_path)
    try:
        with backup_file.open("rb") as source:
            run_command(
                ssh_command(
                    connection,
                    f"umask 077; cat > {quoted_temporary}",
                ),
                stdin=source,
            )
        install_script = (
            f"install -d -o 10001 -g 10001 -m 0750 {APP_DIR}/data && "
            f"install -o 10001 -g 10001 -m 0640 {quoted_temporary} "
            f"{DATABASE_PATH}"
        )
        run_remote(connection, install_script)
    finally:
        try:
            run_command(
                ssh_command(connection, f"rm -f {quoted_temporary}"),
                quiet=True,
            )
        except (OSError, subprocess.CalledProcessError):
            pass


def upload_volume(
    connection: Connection,
    backup: VolumeBackup,
    backup_file: Path,
    overwrite_destination: bool,
) -> None:
    temporary_path = f"/tmp/sal-resources-migration-{backup.label}.tar.gz"
    quoted_temporary = shlex.quote(temporary_path)
    try:
        with backup_file.open("rb") as source:
            run_command(
                ssh_command(connection, f"umask 077; cat > {quoted_temporary}"),
                stdin=source,
            )
        clear_command = (
            "rm -rf /target/* /target/.[!.]* /target/..?*; "
            if overwrite_destination
            else ""
        )
        restore_script = (
            f"docker volume create {shlex.quote(backup.volume_name)} >/dev/null && "
            "docker run --rm --network none "
            f"--volume {shlex.quote(backup.volume_name)}:/target "
            f"--volume {quoted_temporary}:/backup.tar.gz:ro "
            f"{shlex.quote(ARCHIVE_IMAGE)} sh -c "
            f"{shlex.quote(clear_command + 'tar -C /target -xzf /backup.tar.gz')}"
        )
        run_remote(connection, restore_script)
    finally:
        try:
            run_command(
                ssh_command(connection, f"rm -f {quoted_temporary}"),
                quiet=True,
            )
        except (OSError, subprocess.CalledProcessError):
            pass


def clear_optional_destination_volumes(
    connection: Connection,
    source_backups: Sequence[VolumeBackup],
    overwrite_destination: bool,
) -> None:
    if not overwrite_destination:
        return
    source_names = {backup.volume_name for backup in source_backups}
    for backup in VOLUME_BACKUPS:
        if backup.required or backup.volume_name in source_names:
            continue
        clear_script = (
            f"docker volume create {shlex.quote(backup.volume_name)} >/dev/null && "
            "docker run --rm --network none "
            f"--volume {shlex.quote(backup.volume_name)}:/target "
            f"{shlex.quote(ARCHIVE_IMAGE)} sh -c "
            f"{shlex.quote('rm -rf /target/* /target/.[!.]* /target/..?*')}"
        )
        run_remote(connection, clear_script)


def _best_effort_rollback(settings: MigrationSettings) -> None:
    log("Migration failed; stopping the new services and restarting the old stack...")
    try:
        stop_destination_services(settings.destination, quiet=True)
    except (OSError, subprocess.CalledProcessError):
        log("WARNING: could not stop services on the new server.")
    try:
        start_source_services(settings.source)
    except (OSError, subprocess.CalledProcessError) as error:
        raise MigrationError(
            "Automatic rollback failed. Stop the new services and start "
            "the old stack manually."
        ) from error
    log("The old stack has been restarted.")


def migrate(
    settings: MigrationSettings,
    input_stream: Optional[TextIO] = None,
) -> None:
    preflight(settings)
    log("Preparing the new server and pulling images without starting services...")
    configure_server(replace(settings.deployment, prepare_only=True))
    source_volume_backups = available_volume_backups(settings.source)
    confirm_cutover(settings, input_stream)
    source_stopped = False
    try:
        log("Stopping the old bot, Prometheus, and Grafana...")
        stop_source_services(settings.source)
        source_stopped = True
        log(f"Downloading the database to {settings.backup_file}...")
        download_database(settings.source, settings.backup_file)
        validate_database(settings.backup_file)
        log("SQLite integrity check passed.")
        for backup in source_volume_backups:
            archive = volume_backup_path(settings.backup_file, backup)
            log(f"Archiving {backup.label} data to {archive}...")
            download_volume(settings.source, backup, archive)
            validate_volume_backup(archive)
        log("Uploading the database to the new server...")
        upload_database(settings.destination, settings.backup_file)
        for backup in source_volume_backups:
            archive = volume_backup_path(settings.backup_file, backup)
            log(f"Restoring {backup.label} data on the new server...")
            upload_volume(
                settings.destination,
                backup,
                archive,
                settings.overwrite_destination,
            )
        clear_optional_destination_volumes(
            settings.destination,
            source_volume_backups,
            settings.overwrite_destination,
        )
        log("Configuring and starting the new server...")
        configure_server(settings.deployment)
    except (Exception, KeyboardInterrupt):
        if source_stopped:
            _best_effort_rollback(settings)
        raise
    log("Migration completed. The old stateful services remain stopped.")
    log(f"Local database backup: {settings.backup_file}")
    for backup in source_volume_backups:
        log(
            f"Local {backup.label} backup: "
            f"{volume_backup_path(settings.backup_file, backup)}"
        )
