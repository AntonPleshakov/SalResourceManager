"""Command-line settings and local prerequisite validation."""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence


PACKAGE_DIR = Path(__file__).resolve().parent
INFRA_DIR = PACKAGE_DIR.parent
PROJECT_DIR = INFRA_DIR.parent
REMOTE_SCRIPT_FILE = PACKAGE_DIR / "remote.sh"


class ConfigureError(RuntimeError):
    """An expected local configuration error."""


@dataclass(frozen=True)
class Settings:
    target: str
    config_file: Path
    google_credentials_file: Path
    identity_file: Optional[Path]
    port: Optional[int]
    ghcr_username: Optional[str]
    ghcr_token: Optional[str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Configure a new or existing Sal Resources Manager server. "
            "SSH_HOST may be an alias from ~/.ssh/config or user@host."
        )
    )
    parser.add_argument("ssh_host", nargs="?", help="SSH host or config alias")
    parser.add_argument("-c", "--config", help="application config file")
    parser.add_argument(
        "-g",
        "--google-credentials",
        help="Google service account JSON file used for report export",
    )
    parser.add_argument("-i", "--identity", help="SSH identity override")
    parser.add_argument("-p", "--port", help="SSH port override")
    return parser


def _optional_path(value: Optional[str]) -> Optional[Path]:
    return Path(value).expanduser().resolve() if value else None


def _parse_port(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    if not value.isdecimal():
        raise ConfigureError("SSH port must be a number.")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ConfigureError("SSH port must be between 1 and 65535.")
    return port


def resolve_settings(
    argv: Optional[Sequence[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Settings:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    target = args.ssh_host or env.get("SSH_TARGET", "")

    if not target:
        raise ConfigureError("SSH host or SSH config alias is required.")
    if target.startswith("-") or any(character.isspace() for character in target):
        raise ConfigureError("SSH host must not begin with '-' or contain whitespace.")

    username = env.get("GHCR_USERNAME") or None
    token = env.get("GHCR_TOKEN") or None
    if bool(username) != bool(token):
        raise ConfigureError("GHCR_USERNAME and GHCR_TOKEN must be set together.")
    if any("\n" in value or "\r" in value for value in (username, token) if value):
        raise ConfigureError("GHCR credentials must not contain line breaks.")

    config_file = _optional_path(
        args.config or env.get("CONFIG_FILE") or str(PROJECT_DIR / "config/config.ini")
    )
    google_credentials_file = _optional_path(
        args.google_credentials
        or env.get("GOOGLE_CREDENTIALS_FILE")
        or str(PROJECT_DIR / "gapi_service_file.json")
    )
    identity_file = _optional_path(args.identity or env.get("SSH_IDENTITY_FILE"))
    port = _parse_port(args.port or env.get("SSH_PORT"))

    assert config_file is not None
    assert google_credentials_file is not None
    return Settings(
        target=target,
        config_file=config_file,
        google_credentials_file=google_credentials_file,
        identity_file=identity_file,
        port=port,
        ghcr_username=username,
        ghcr_token=token,
    )


def require_local_prerequisites(settings: Settings) -> None:
    for command in ("ssh", "scp"):
        if shutil.which(command) is None:
            raise ConfigureError(f"Required command not found: {command}")

    files = [
        PROJECT_DIR / "compose.yaml",
        REMOTE_SCRIPT_FILE,
        settings.config_file,
        settings.google_credentials_file,
    ]
    if settings.identity_file:
        files.append(settings.identity_file)
    for path in files:
        if not path.is_file():
            raise ConfigureError(f"Required file not found: {path}")
