"""Command-line settings for server migration."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from infra.configure_server.settings import (
    PROJECT_DIR,
    ConfigureError,
    Settings as ConfigureSettings,
)


DEFAULT_BACKUP_FILE = PROJECT_DIR / "sal_resources.db.backup"


@dataclass(frozen=True)
class Connection:
    target: str
    identity_file: Optional[Path]
    port: Optional[int]


@dataclass(frozen=True)
class MigrationSettings:
    source: Connection
    destination: Connection
    deployment: ConfigureSettings
    backup_file: Path
    overwrite_destination: bool
    assume_yes: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stop stateful services on the old server, transfer SQLite and "
            "monitoring data, and configure the new server."
        )
    )
    parser.add_argument("source", help="old SSH host or SSH config alias")
    parser.add_argument("destination", help="new SSH host or SSH config alias")
    parser.add_argument("-c", "--config", help="config with the new WEBHOOK_URL")
    parser.add_argument("-g", "--google-oauth-token", help="Google OAuth token")
    parser.add_argument("--source-identity", help="old-server SSH identity")
    parser.add_argument("--source-port", help="old-server SSH port")
    parser.add_argument("-i", "--identity", help="new-server SSH identity")
    parser.add_argument("-p", "--port", help="new-server SSH port")
    parser.add_argument("--backup", help="local database backup path")
    parser.add_argument(
        "--overwrite-destination",
        action="store_true",
        help="replace an existing database on the new server",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="skip the cutover confirmation",
    )
    return parser


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _optional_path(value: Optional[str]) -> Optional[Path]:
    return _path(value) if value else None


def _port(value: Optional[str], name: str) -> Optional[int]:
    if not value:
        return None
    if not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ConfigureError(f"{name} must be between 1 and 65535.")
    return int(value)


def _target(value: str, name: str) -> str:
    if value.startswith("-") or any(character.isspace() for character in value):
        raise ConfigureError(
            f"{name} must not begin with '-' or contain whitespace."
        )
    return value


def resolve_settings(
    argv: Optional[Sequence[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> MigrationSettings:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    source_identity = _optional_path(
        args.source_identity or env.get("SOURCE_SSH_IDENTITY_FILE")
    )
    destination_identity = _optional_path(
        args.identity or env.get("SSH_IDENTITY_FILE")
    )
    config_file = _path(
        args.config
        or env.get("CONFIG_FILE")
        or str(PROJECT_DIR / "config/config.ini")
    )
    google_token = _path(
        args.google_oauth_token
        or env.get("GOOGLE_OAUTH_TOKEN_FILE")
        or str(PROJECT_DIR / "config/google_oauth_token.json")
    )
    backup_file = _path(
        args.backup
        or env.get("MIGRATION_BACKUP_FILE")
        or str(DEFAULT_BACKUP_FILE)
    )
    username = env.get("GHCR_USERNAME") or None
    token = env.get("GHCR_TOKEN") or None
    if bool(username) != bool(token):
        raise ConfigureError("GHCR_USERNAME and GHCR_TOKEN must be set together.")

    source = Connection(
        target=_target(args.source, "source"),
        identity_file=source_identity,
        port=_port(args.source_port or env.get("SOURCE_SSH_PORT"), "source port"),
    )
    destination = Connection(
        target=_target(args.destination, "destination"),
        identity_file=destination_identity,
        port=_port(args.port or env.get("SSH_PORT"), "destination port"),
    )
    if source.target == destination.target:
        raise ConfigureError("Source and destination SSH hosts must differ.")

    deployment = ConfigureSettings(
        target=destination.target,
        config_file=config_file,
        google_oauth_token_file=google_token,
        identity_file=destination.identity_file,
        port=destination.port,
        ghcr_username=username,
        ghcr_token=token,
    )
    return MigrationSettings(
        source=source,
        destination=destination,
        deployment=deployment,
        backup_file=backup_file,
        overwrite_destination=args.overwrite_destination,
        assume_yes=args.yes,
    )
