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
`sudo` access. Set a static public IPv4 address in `WEBHOOK_URL` and prepare
`config/config.ini` and `config/google_oauth_token.json`.

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
application data. Provider firewalls must allow inbound TCP ports `8443` and
`3000`.

Re-run the command after configuration or public-IP changes and periodically
to renew the webhook certificate.
