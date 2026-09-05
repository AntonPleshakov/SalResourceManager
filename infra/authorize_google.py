"""Create the authorized-user token used by the report exporter."""

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from google_auth_oauthlib.flow import InstalledAppFlow


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_FILE = PROJECT_DIR / "config/google_oauth_client.json"
DEFAULT_TOKEN_FILE = PROJECT_DIR / "config/google_oauth_token.json"
GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
)


def _load_client_config(client_file: Path) -> dict:
    try:
        payload = json.loads(client_file.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"OAuth client file not found: {client_file}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Unable to read OAuth client file: {client_file}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("OAuth client file must contain a JSON object")
    return payload


def _validate_client_config(payload: dict) -> None:
    if "installed" not in payload:
        raise RuntimeError(
            "OAuth client must have the Desktop app application type"
        )


def _write_token(token_file: Path, serialized_credentials: str) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = token_file.with_suffix(f"{token_file.suffix}.tmp")
    temporary_file.write_text(serialized_credentials, encoding="utf-8")
    os.chmod(temporary_file, 0o600)
    temporary_file.replace(token_file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authorize the report exporter to use a Google account."
    )
    parser.add_argument(
        "--client-file",
        type=Path,
        default=DEFAULT_CLIENT_FILE,
        help="OAuth client JSON downloaded from Google Cloud Console",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DEFAULT_TOKEN_FILE,
        help="destination for the generated authorized-user token",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing token file",
    )
    return parser


def authorize(
    client_file: Path,
    token_file: Path,
    *,
    force: bool,
) -> None:
    if token_file.exists() and not force:
        raise RuntimeError(
            f"Token file already exists: {token_file}. Use --force to replace it."
        )
    client_config = _load_client_config(client_file)
    _validate_client_config(client_config)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file),
        GOOGLE_OAUTH_SCOPES,
    )
    credentials = flow.run_local_server(
        port=0,
        open_browser=True,
        timeout_seconds=600,
        access_type="offline",
        prompt="consent",
    )
    if not credentials.refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token; revoke the app grant and retry"
        )
    _write_token(token_file, credentials.to_json())
    print(f"Google OAuth token saved to {token_file}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        authorize(
            args.client_file.resolve(),
            args.token_file.resolve(),
            force=args.force,
        )
    except RuntimeError as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
