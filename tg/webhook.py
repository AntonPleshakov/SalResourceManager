import logging
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from telebot import TeleBot

from config.config import getconf


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEBHOOK_LISTEN = "0.0.0.0"
WEBHOOK_PORT = 8443
WEBHOOK_CERTIFICATE_PATH = _PROJECT_ROOT / "certs" / "webhook.pem"
WEBHOOK_PRIVATE_KEY_PATH = _PROJECT_ROOT / "certs" / "webhook.key"
_SECRET_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_INVALID_HTTP_REQUEST_MESSAGE = "Invalid HTTP request received."


class InvalidHTTPRequestWarningFilter(logging.Filter):
    """Drop malformed-request noise from clients scanning the public port."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.name == "uvicorn.error"
            and record.levelno == logging.WARNING
            and record.getMessage() == _INVALID_HTTP_REQUEST_MESSAGE
        )


@dataclass(frozen=True)
class WebhookSettings:
    public_url: str
    listen: str
    port: int
    url_path: str
    secret_token: str
    certificate_path: Path
    private_key_path: Path


def generate_webhook_secret_token() -> str:
    return secrets.token_urlsafe(32)


def build_webhook_settings(
    public_url: str,
    listen: str,
    port: int,
    secret_token: str,
    certificate_path: Path,
    private_key_path: Path,
) -> WebhookSettings:
    parsed_url = urlsplit(public_url.strip())
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ValueError("WEBHOOK_URL must be an absolute HTTPS URL")
    if parsed_url.username or parsed_url.password:
        raise ValueError("WEBHOOK_URL must not contain credentials")
    if parsed_url.query or parsed_url.fragment:
        raise ValueError("WEBHOOK_URL must not contain a query or fragment")

    url_path = parsed_url.path.strip("/")
    if not url_path:
        raise ValueError("WEBHOOK_URL must contain a non-empty path")
    if not listen.strip():
        raise ValueError("WEBHOOK_LISTEN must not be empty")
    if not 1 <= port <= 65535:
        raise ValueError("WEBHOOK_PORT must be between 1 and 65535")
    if not _SECRET_TOKEN_PATTERN.fullmatch(secret_token):
        raise ValueError(
            "Webhook secret token must contain 1-256 letters, digits, "
            "underscores or hyphens"
        )

    normalized_url = urlunsplit(
        (parsed_url.scheme, parsed_url.netloc, f"/{url_path}/", "", "")
    )
    return WebhookSettings(
        public_url=normalized_url,
        listen=listen.strip(),
        port=port,
        url_path=url_path,
        secret_token=secret_token,
        certificate_path=certificate_path,
        private_key_path=private_key_path,
    )


def load_webhook_settings() -> WebhookSettings:
    settings = build_webhook_settings(
        public_url=getconf("WEBHOOK_URL"),
        listen=WEBHOOK_LISTEN,
        port=WEBHOOK_PORT,
        secret_token=generate_webhook_secret_token(),
        certificate_path=WEBHOOK_CERTIFICATE_PATH,
        private_key_path=WEBHOOK_PRIVATE_KEY_PATH,
    )
    for option, path in (
        ("WEBHOOK_CERTIFICATE_PATH", settings.certificate_path),
        ("WEBHOOK_PRIVATE_KEY_PATH", settings.private_key_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{option} does not exist: {path}")
    return settings


def configure_uvicorn_logging() -> None:
    # pyTelegramBotAPI does not expose Uvicorn's access_log option. Its
    # listener calls uvicorn.run() with the default logging configuration, so
    # adjust that configuration before the listener is created.
    from uvicorn.config import LOGGING_CONFIG

    LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"] = "WARNING"
    LOGGING_CONFIG.setdefault("filters", {})["invalid_http_request"] = {
        "()": InvalidHTTPRequestWarningFilter,
    }
    default_handler = LOGGING_CONFIG["handlers"]["default"]
    handler_filters = default_handler.setdefault("filters", [])
    if "invalid_http_request" not in handler_filters:
        handler_filters.append("invalid_http_request")


def serve_webhook(bot: TeleBot, settings: WebhookSettings) -> None:
    configure_uvicorn_logging()
    bot.run_webhooks(
        listen=settings.listen,
        port=settings.port,
        url_path=settings.url_path,
        webhook_url=settings.public_url,
        secret_token=settings.secret_token,
        certificate=str(settings.certificate_path),
        certificate_key=str(settings.private_key_path),
        max_connections=1,
        drop_pending_updates=False,
    )
