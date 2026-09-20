#!/usr/bin/env python3
"""Move Sal Resources Manager to another server."""

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from infra.migrate_server.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
