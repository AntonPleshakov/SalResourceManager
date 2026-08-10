import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "infra"
    / "configure_server"
    / "generate-webhook-certificate.sh"
)

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("openssl") is None,
    reason="The certificate generator requires Bash and OpenSSL on Linux",
)


def run_generator(tmp_path: Path, public_ip: str) -> subprocess.CompletedProcess:
    certificate = tmp_path / "webhook.pem"
    private_key = tmp_path / "webhook.key"
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            public_ip,
            str(certificate),
            str(private_key),
            str(os.getuid()),
            str(os.getgid()),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_certificate_generator_creates_and_reuses_matching_pair(tmp_path):
    first_run = run_generator(tmp_path, "203.0.113.10")

    assert first_run.stdout.strip() == "generated"
    certificate = tmp_path / "webhook.pem"
    private_key = tmp_path / "webhook.key"
    assert certificate.is_file()
    assert private_key.is_file()
    assert stat.S_IMODE(private_key.stat().st_mode) == 0o400

    certificate_details = subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            str(certificate),
            "-noout",
            "-ext",
            "subjectAltName",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "IP Address:203.0.113.10" in certificate_details.stdout

    second_run = run_generator(tmp_path, "203.0.113.10")

    assert second_run.stdout.strip() == "current"


def test_certificate_generator_replaces_certificate_when_ip_changes(tmp_path):
    run_generator(tmp_path, "203.0.113.10")

    result = run_generator(tmp_path, "203.0.113.11")

    assert result.stdout.strip() == "generated"
    certificate_details = subprocess.run(
        [
            "openssl",
            "x509",
            "-in",
            str(tmp_path / "webhook.pem"),
            "-noout",
            "-ext",
            "subjectAltName",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "IP Address:203.0.113.11" in certificate_details.stdout
