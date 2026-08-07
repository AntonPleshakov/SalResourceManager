"""Command-line entry point for server configuration."""

from __future__ import annotations

import subprocess
import sys
from typing import Optional, Sequence

from .settings import ConfigureError, resolve_settings
from .transport import configure_server


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        settings = resolve_settings(argv)
        configure_server(settings)
    except ConfigureError as error:
        print(f"[configure] ERROR: {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(
            f"[configure] ERROR: command failed with exit code {error.returncode}.",
            file=sys.stderr,
        )
        return error.returncode or 1
    except OSError as error:
        print(
            f"[configure] ERROR: failed to run a local command: {error}",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\n[configure] Interrupted.", file=sys.stderr)
        return 130
    return 0
