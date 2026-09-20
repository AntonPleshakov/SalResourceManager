import logging
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import uvicorn
from telebot import TeleBot
from telebot.ext.sync import SyncWebhookListener

from config.config import getconf
from tg.metrics import WebhookMetricsMiddleware
from tg.update_types import ALLOWED_UPDATES


WEBHOOK_LISTEN = "0.0.0.0"
WEBHOOK_PORT = 8443
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


def generate_webhook_secret_token() -> str:
    return secrets.token_urlsafe(32)


def build_webhook_settings(
    public_url: str,
    listen: str,
    port: int,
    secret_token: str,
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
    )


def load_webhook_settings() -> WebhookSettings:
    settings = build_webhook_settings(
        public_url=getconf("WEBHOOK_URL"),
        listen=WEBHOOK_LISTEN,
        port=WEBHOOK_PORT,
        secret_token=generate_webhook_secret_token(),
    )
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


def build_webhook_listener(
    bot: TeleBot, settings: WebhookSettings
) -> SyncWebhookListener:
    bot.set_webhook(
        url=settings.public_url,
        max_connections=1,
        drop_pending_updates=False,
        secret_token=settings.secret_token,
        allowed_updates=list(ALLOWED_UPDATES),
    )

    webhook_path = f"/{settings.url_path}/"
    listener = SyncWebhookListener(
        bot=bot,
        secret_token=settings.secret_token,
        host=settings.listen,
        port=settings.port,
        ssl_context=None,
        url_path=webhook_path,
    )
    listener.app.add_middleware(
        WebhookMetricsMiddleware,
        webhook_path=webhook_path,
    )
    bot.webhook_listener = listener
    return listener


def serve_webhook(bot: TeleBot, settings: WebhookSettings) -> None:
    configure_uvicorn_logging()
    listener = build_webhook_listener(bot, settings)
    uvicorn.run(
        app=listener.app,
        host=settings.listen,
        port=settings.port,
    )
