"""Command-line entry point for server migration."""

from __future__ import annotations

import subprocess
import sys
from typing import Optional, Sequence

from infra.configure_server.settings import ConfigureError

from .migration import MigrationError, migrate
from .settings import resolve_settings


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        settings = resolve_settings(argv)
        migrate(settings)
    except (ConfigureError, MigrationError) as error:
        print(f"[migrate] ERROR: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(
            f"[migrate] ERROR: command failed with exit code {error.returncode}.",
            file=sys.stderr,
        )
        return error.returncode or 1
    except OSError as error:
        print(f"[migrate] ERROR: local operation failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[migrate] Interrupted.", file=sys.stderr)
        return 130
    return 0
