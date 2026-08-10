from pathlib import Path
from unittest.mock import Mock

import pytest

from tg.webhook import (
    build_webhook_settings,
    generate_webhook_secret_token,
    serve_webhook,
)


def test_generated_webhook_secret_token_is_telegram_compatible():
    token = generate_webhook_secret_token()

    assert 1 <= len(token) <= 256
    assert token.replace("_", "").replace("-", "").isalnum()


def test_webhook_settings_normalize_the_public_url():
    settings = build_webhook_settings(
        "https://bot.example.com/telegram",
        "0.0.0.0",
        8443,
        "valid_secret-token",
        Path("certificate.pem"),
        Path("private.key"),
    )

    assert settings.public_url == "https://bot.example.com/telegram/"
    assert settings.url_path == "telegram"


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("http://bot.example.com/telegram", "absolute HTTPS URL"),
        ("https://bot.example.com", "non-empty path"),
        ("https://bot.example.com/telegram?key=value", "query or fragment"),
    ],
)
def test_webhook_settings_reject_invalid_public_urls(url, error):
    with pytest.raises(ValueError, match=error):
        build_webhook_settings(
            url,
            "0.0.0.0",
            8443,
            "valid-secret",
            Path("certificate.pem"),
            Path("private.key"),
        )


def test_webhook_settings_reject_invalid_secret_token():
    with pytest.raises(ValueError, match="Webhook secret token"):
        build_webhook_settings(
            "https://bot.example.com/telegram",
            "0.0.0.0",
            8443,
            "not valid",
            Path("certificate.pem"),
            Path("private.key"),
        )


def test_serve_webhook_registers_and_starts_listener():
    bot = Mock()
    settings = build_webhook_settings(
        "https://bot.example.com/telegram",
        "0.0.0.0",
        8443,
        "valid-secret",
        Path("certificate.pem"),
        Path("private.key"),
    )

    serve_webhook(bot, settings)

    bot.run_webhooks.assert_called_once_with(
        listen="0.0.0.0",
        port=8443,
        url_path="telegram",
        webhook_url="https://bot.example.com/telegram/",
        secret_token="valid-secret",
        certificate="certificate.pem",
        certificate_key="private.key",
        max_connections=1,
        drop_pending_updates=False,
    )
