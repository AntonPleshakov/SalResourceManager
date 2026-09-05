import json

import pytest

from infra import authorize_google


class FakeCredentials:
    refresh_token = "refresh-token"

    @staticmethod
    def to_json():
        return json.dumps({"refresh_token": "refresh-token"})


class FakeFlow:
    def __init__(self):
        self.run_arguments = None

    def run_local_server(self, **kwargs):
        self.run_arguments = kwargs
        return FakeCredentials()


def write_client_file(path, client_type="installed", redirect_uris=None):
    client = {"client_id": "id", "client_secret": "secret"}
    if redirect_uris is not None:
        client["redirect_uris"] = redirect_uris
    path.write_text(json.dumps({client_type: client}), encoding="utf-8")


def test_authorize_writes_refresh_token_and_opens_local_browser(
    monkeypatch,
    tmp_path,
):
    client_file = tmp_path / "client.json"
    token_file = tmp_path / "token.json"
    write_client_file(client_file)
    flow = FakeFlow()

    def create_flow(path, scopes):
        assert path == str(client_file)
        assert scopes == authorize_google.GOOGLE_OAUTH_SCOPES
        return flow

    monkeypatch.setattr(
        authorize_google.InstalledAppFlow,
        "from_client_secrets_file",
        create_flow,
    )

    authorize_google.authorize(
        client_file,
        token_file,
        force=False,
    )

    assert json.loads(token_file.read_text(encoding="utf-8")) == {
        "refresh_token": "refresh-token"
    }
    assert flow.run_arguments["port"] == 0
    assert flow.run_arguments["open_browser"] is True
    assert flow.run_arguments["access_type"] == "offline"
    assert flow.run_arguments["prompt"] == "consent"


def test_authorize_requires_desktop_client(tmp_path):
    client_file = tmp_path / "client.json"
    write_client_file(client_file, client_type="web")

    with pytest.raises(RuntimeError, match="Desktop app"):
        authorize_google.authorize(
            client_file,
            tmp_path / "token.json",
            force=False,
        )


def test_authorize_does_not_replace_token_without_force(tmp_path):
    client_file = tmp_path / "client.json"
    token_file = tmp_path / "token.json"
    write_client_file(client_file)
    token_file.write_text("existing", encoding="utf-8")

    with pytest.raises(RuntimeError, match="already exists"):
        authorize_google.authorize(
            client_file,
            token_file,
            force=False,
        )
