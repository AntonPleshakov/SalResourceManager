import os
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


PROJECT_DIR = Path(__file__).parents[1]
GRAFANA_FILES = (
    "datasources.yml", "dashboards.yml", "sal-resource-manager.json",
    "sal-resource-manager-system.json", "sal-resource-manager-logs.json",
)
IMAGE = "ghcr.io/antonpleshakov/salresourcemanager:sha-" + "a" * 40


def find_bash():
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


@pytest.fixture
def deployment(tmp_path):
    bash = find_bash()
    if bash is None:
        pytest.skip("Bash is required to exercise the Linux deployment script")
    release = tmp_path / "release"
    app = tmp_path / "app"
    binaries = tmp_path / "bin"
    for directory in (release / "config/grafana", app / "config/grafana", binaries):
        directory.mkdir(parents=True)
    for filename in GRAFANA_FILES:
        content = (PROJECT_DIR / "config/grafana" / filename).read_bytes()
        (release / "config/grafana" / filename).write_bytes(content)
        (app / "config/grafana" / filename).write_bytes(content)
    (release / "release-image.txt").write_text(IMAGE + "\n", newline="\n")
    (app / "config/grafana/grafana.ini").write_text("server-only credentials")
    log = tmp_path / "docker.log"
    failure = tmp_path / "failure"
    docker = binaries / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'printf "%s|%s\\n" "$BOT_IMAGE" "$*" >> "$DEPLOY_TEST_LOG"\n'
        'if [ -f "$DEPLOY_TEST_FAILURE" ]; then\n'
        '  case "$*" in\n'
        '    "compose pull bot") [ "$(cat "$DEPLOY_TEST_FAILURE")" != pull ] || exit 1 ;;\n'
        '    *"120 bot") [ "$(cat "$DEPLOY_TEST_FAILURE")" != bot ] || exit 1 ;;\n'
        '    *grafana) [ "$(cat "$DEPLOY_TEST_FAILURE")" != grafana ] || exit 1 ;;\n'
        '    "image rm "*) [ "$(cat "$DEPLOY_TEST_FAILURE")" != cleanup ] || exit 1 ;;\n'
        '  esac\n'
        'fi\n'
        'case "$*" in\n'
        '  "compose ps -aq bot") echo previous-container ;;\n'
        '  "inspect --format {{.Image}} previous-container") echo "${DEPLOY_TEST_PREVIOUS:-previous-id}" ;;\n'
        '  "image inspect --format {{.Id}} "*":rollback")\n'
        '    if [ -f "$DEPLOY_TEST_ROLLBACK" ]; then cat "$DEPLOY_TEST_ROLLBACK"; else echo old-rollback-id; fi ;;\n'
        '  "image inspect --format {{.Id}} "*) echo current-id ;;\n'
        '  "image tag "*) printf "%s\\n" "$3" > "$DEPLOY_TEST_ROLLBACK" ;;\n'
        '  "image ls "*)\n'
        '    repo=ghcr.io/antonpleshakov/salresourcemanager\n'
        '    printf "%s\\n" "$repo:current current-id" "$repo:previous previous-id" '
        '"$repo:rollback $(cat "$DEPLOY_TEST_ROLLBACK" 2>/dev/null || echo old-rollback-id)" '
        '"$repo:obsolete obsolete-id" "$repo:in-use in-use-id" ;;\n'
        '  "ps -aq --filter ancestor=in-use-id") echo another-container ;;\n'
        '  "image inspect --format {{json .RepoTags}} old-rollback-id") echo "[]" ;;\n'
        'esac\n',
        encoding="utf-8", newline="\n",
    )
    docker.chmod(0o755)
    if os.name == "nt":
        # Git Bash cannot apply Linux directory modes to Windows test folders.
        installer = binaries / "install"
        installer.write_text(
            '#!/bin/sh\ncase "$1" in\n'
            '  -d) mkdir -p "$4" ;;\n'
            '  -m) cp "$3" "$4" ;;\n'
            '  *) exit 1 ;;\nesac\n',
            encoding="utf-8", newline="\n",
        )
        installer.chmod(0o755)
    return bash, release, app, binaries, log, failure


def run_deploy(deployment, **overrides):
    bash, release, app, binaries, log, failure = deployment
    environment = {
        **os.environ,
        "DEPLOY_TEST_LOG": log.as_posix(),
        "DEPLOY_TEST_FAILURE": failure.as_posix(),
        "DEPLOY_TEST_ROLLBACK": (app / "rollback-id").as_posix(),
        **overrides,
    }
    return subprocess.run(
        [bash, "-c",
         'if command -v cygpath >/dev/null 2>&1; then test_bin=$(cygpath -u "$1"); '
         'else test_bin=$1; fi; export PATH="$test_bin:$PATH"; exec sh "$2" "$3" "$4"', "deploy-test",
         binaries.as_posix(), (PROJECT_DIR / "infra/deploy.sh").as_posix(),
         release.as_posix(), app.as_posix()],
        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )


def docker_calls(deployment):
    log = deployment[4]
    return [line.split("|", 1) for line in log.read_text().splitlines()] if log.exists() else []


def test_changed_dashboards_recreate_grafana_and_pin_bot_image(deployment):
    _, release, app, _, log, _ = deployment
    dashboard = app / "config/grafana/sal-resource-manager.json"
    dashboard.write_text("old dashboard")
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stderr
    calls = docker_calls(deployment)
    assert [command for _, command in calls if command.startswith("compose ")] == [
        "compose ps -aq bot", "compose pull bot",
        "compose up -d --force-recreate --wait --wait-timeout 120 bot",
        "compose up -d --no-deps --force-recreate --wait --wait-timeout 120 grafana",
    ]
    assert all(image == IMAGE for image, _ in calls)
    assert dashboard.read_bytes() == (release / "config/grafana" / dashboard.name).read_bytes()
    assert (app / "config/grafana/grafana.ini").read_text() == "server-only credentials"
    assert not (app / "config/grafana/.recreate-required").exists()
    log.write_text("")
    assert run_deploy(deployment).returncode == 0
    assert all("grafana" not in command for _, command in docker_calls(deployment))


def test_failed_grafana_recreation_is_retried_on_next_deploy(deployment):
    _, _, app, _, log, failure = deployment
    (app / "config/grafana/datasources.yml").write_text("old datasource")
    failure.write_text("grafana")
    assert run_deploy(deployment).returncode != 0
    marker = app / "config/grafana/.recreate-required"
    assert marker.exists()
    failure.unlink()
    log.write_text("")
    assert run_deploy(deployment).returncode == 0
    assert any(command.endswith(" grafana") for _, command in docker_calls(deployment))
    assert not marker.exists()


@pytest.mark.parametrize("failure_kind", ["pull", "incomplete_upload"])
def test_release_failure_keeps_installed_configuration(deployment, failure_kind):
    _, release, app, _, _, failure = deployment
    dashboard = app / "config/grafana/sal-resource-manager.json"
    dashboard.write_text("installed dashboard")
    if failure_kind == "pull":
        failure.write_text("pull")
    else:
        (release / "config/grafana/datasources.yml").unlink()
    assert run_deploy(deployment).returncode != 0
    assert dashboard.read_text() == "installed dashboard"
    assert not (app / "config/grafana/.recreate-required").exists()
    assert all("up" not in command for _, command in docker_calls(deployment))


def test_cleanup_keeps_current_previous_and_images_used_by_other_containers(deployment):
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stderr
    commands = [command for _, command in docker_calls(deployment)]
    repo = "ghcr.io/antonpleshakov/salresourcemanager"
    assert f"image tag previous-id {repo}:rollback" in commands
    assert [command for command in commands if command.startswith("image rm ")] == [
        f"image rm {repo}:obsolete", "image rm old-rollback-id",
    ]
    assert commands.index(f"image rm {repo}:obsolete") > commands.index(
        "compose up -d --force-recreate --wait --wait-timeout 120 bot"
    )


def test_redeploying_current_image_preserves_existing_rollback(deployment):
    result = run_deploy(deployment, DEPLOY_TEST_PREVIOUS="current-id")
    assert result.returncode == 0, result.stderr
    commands = [command for _, command in docker_calls(deployment)]
    assert not any(command.startswith("image tag ") for command in commands)
    assert "image rm old-rollback-id" not in commands
    assert not any(command.endswith(":rollback") for command in commands if command.startswith("image rm "))


@pytest.mark.parametrize("failure_kind", ["pull", "bot", "grafana"])
def test_failed_deploy_does_not_clean_images_or_replace_rollback(deployment, failure_kind):
    _, _, app, _, _, failure = deployment
    (app / "config/grafana/datasources.yml").write_text("old datasource")
    failure.write_text(failure_kind)
    assert run_deploy(deployment).returncode != 0
    commands = [command for _, command in docker_calls(deployment)]
    assert not any(command.startswith(("image rm ", "image tag ")) for command in commands)


def test_cleanup_failure_does_not_fail_successful_deploy(deployment):
    deployment[5].write_text("cleanup")
    result = run_deploy(deployment)
    assert result.returncode == 0
    assert "old application images could not be fully cleaned up" in result.stderr


def test_workflow_uploads_release_configuration_with_matching_image_tag():
    bash = find_bash()
    if bash is None:
        pytest.skip("Bash is required for workflow syntax validation")
    workflow = (PROJECT_DIR / ".github/workflows/deploy.yml").read_text()
    script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
    result = subprocess.run([bash, "-n"], input=script, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "ref: ${{ github.sha }}" in workflow
    assert "salresourcemanager:sha-${{ github.sha }}" in workflow
    assert "config/grafana/*.json config/grafana/*.yml infra/deploy.sh release-image.txt" in script
    assert "grafana.ini" not in script
    assert "type=sha,format=long" in (PROJECT_DIR / ".github/workflows/docker-publish.yml").read_text()
