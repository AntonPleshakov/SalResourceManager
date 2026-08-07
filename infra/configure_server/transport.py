"""SSH transport and remote configuration orchestration."""

from __future__ import annotations

import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Sequence

from .settings import (
    PROJECT_DIR,
    REMOTE_SCRIPT_FILE,
    Settings,
    require_local_prerequisites,
)


def ssh_options(settings: Settings) -> list[str]:
    options = ["-o", "BatchMode=yes"]
    if settings.identity_file:
        options.extend(("-i", str(settings.identity_file)))
    if settings.port:
        options.extend(("-p", str(settings.port)))
    return options


def scp_options(settings: Settings) -> list[str]:
    options = ["-o", "BatchMode=yes"]
    if settings.identity_file:
        options.extend(("-i", str(settings.identity_file)))
    if settings.port:
        options.extend(("-P", str(settings.port)))
    return options


def ssh_command(settings: Settings, remote_command: str) -> list[str]:
    return ["ssh", *ssh_options(settings), settings.target, remote_command]


def scp_command(settings: Settings, source: Path, destination: str) -> list[str]:
    return [
        "scp",
        *scp_options(settings),
        str(source),
        f"{settings.target}:{destination}",
    ]


def run_command(
    command: Sequence[str],
    *,
    input_text: Optional[str] = None,
    quiet: bool = False,
) -> None:
    subprocess.run(
        command,
        check=True,
        input=input_text,
        text=True,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )


def log(message: str) -> None:
    print(f"[configure] {message}", flush=True)


def configure_server(settings: Settings) -> None:
    require_local_prerequisites(settings)
    remote_dir = f"/tmp/sal-resource-manager-configure-{uuid.uuid4().hex}"
    quoted_dir = shlex.quote(remote_dir)
    remote_created = False

    try:
        log(f"Connecting to SSH host {settings.target}...")
        run_command(ssh_command(settings, f"install -d -m 0700 {quoted_dir}"))
        remote_created = True

        log("Copying the desired server configuration...")
        uploads = (
            (REMOTE_SCRIPT_FILE, "configure-remote.sh"),
            (PROJECT_DIR / "compose.yaml", "compose.yaml"),
            (settings.config_file, "config.ini"),
            (settings.google_credentials_file, "gapi_service_file.json"),
        )
        for source, name in uploads:
            run_command(scp_command(settings, source, f"{remote_dir}/{name}"))

        if settings.ghcr_username and settings.ghcr_token:
            credentials = f"{settings.ghcr_username}\n{settings.ghcr_token}\n"
            command = f"umask 077; cat > {quoted_dir}/ghcr-credentials"
            run_command(ssh_command(settings, command), input_text=credentials)

        log("Applying the desired state on the server...")
        remote_script = f"{quoted_dir}/configure-remote.sh"
        remote_apply = (
            'if [ "$(id -u)" -eq 0 ]; then '
            f"bash {remote_script} {quoted_dir}; "
            "else "
            f"sudo -n bash {remote_script} {quoted_dir}; "
            "fi"
        )
        run_command(ssh_command(settings, remote_apply))
    finally:
        if remote_created:
            _cleanup_remote_files(settings, remote_dir, quoted_dir)


def _cleanup_remote_files(
    settings: Settings,
    remote_dir: str,
    quoted_dir: str,
) -> None:
    names = (
        "configure-remote.sh",
        "compose.yaml",
        "config.ini",
        "gapi_service_file.json",
        "ghcr-credentials",
    )
    quoted_files = " ".join(
        shlex.quote(f"{remote_dir}/{name}") for name in names
    )
    cleanup = f"rm -f {quoted_files}; rmdir {quoted_dir} 2>/dev/null || true"
    try:
        run_command(ssh_command(settings, cleanup), quiet=True)
    except (OSError, subprocess.CalledProcessError):
        # Cleanup is best-effort and must not hide the original failure.
        pass
