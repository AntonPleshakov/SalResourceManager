# Server deployment

## Google authorization

Create a [Desktop OAuth client](https://console.cloud.google.com/auth/clients)
and save the downloaded JSON as `config/google_oauth_client.json`. Install the
project dependencies and authorize the Google account once:

```bash
python -m pip install -r requirements.txt
python -m infra.authorize_google
```

Keep the OAuth consent screen in production status so the refresh token does
not expire after seven days. Neither OAuth JSON file belongs in Git or the
application image.

## Configure server

The remote host requires Docker Engine and a user with root or passwordless
`sudo` access. Set a public DNS name in `WEBHOOK_URL` and prepare
`config/config.ini` and `config/google_oauth_token.json`. The DNS name must
resolve to the server's public address before deployment.

Configure or update the host:

```bash
python infra/configure-server.py user@server
```

An SSH config alias is supported:

```sshconfig
Host sal-production
    HostName example.com
    User deploy
    IdentityFile ~/.ssh/sal_resource_manager
```

```bash
python infra/configure-server.py sal-production
```

Use `-c`, `-g`, `-i`, and `-p` to override the application config, Google OAuth
token, SSH identity, and SSH port. The equivalent environment variables are
`CONFIG_FILE`, `GOOGLE_OAUTH_TOKEN_FILE`, `SSH_IDENTITY_FILE`, and `SSH_PORT`.
Private registries additionally use `GHCR_USERNAME` and `GHCR_TOKEN`.

Persistent files are stored under `/opt/sal-resource-manager`. Back up and
restore `data/sal_resources.db` when replacing a host; deployment does not copy
application data. Provider firewalls must allow inbound TCP ports `80` and
`8443`; UDP `8443` enables HTTP/3. Port `443` is left untouched for the Telegram
proxy. Caddy obtains and renews the public certificate over port `80`, and
Grafana is available at the root of the webhook domain on port `8443`.
Configuration creates 1 GiB of swap when the host has no active swap. Container
logs are available through the VictoriaLogs data source in Grafana.

## Replace a server

Set the new public DNS name in `config/config.ini`, then run:

```bash
python infra/migrate-server.py old-host new-host
```

The command checks both hosts, prepares the new host without starting services,
stops the old stateful services, verifies and transfers SQLite and monitoring
volumes, and starts the new host. It restarts the old stack if migration fails.
Use `--help` for separate SSH identities, ports, and backup location.
