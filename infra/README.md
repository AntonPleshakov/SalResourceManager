# Server deployment

The remote host requires Docker Engine and a user with root or passwordless
`sudo` access. Set a static public IPv4 address in `WEBHOOK_URL` and prepare
`config/config.ini` and `gapi_service_file.json`.

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

Use `-c`, `-g`, `-i`, and `-p` to override the application config, Google
credentials, SSH identity, and SSH port. The equivalent environment variables
are `CONFIG_FILE`, `GOOGLE_CREDENTIALS_FILE`, `SSH_IDENTITY_FILE`, and
`SSH_PORT`. Private registries additionally use `GHCR_USERNAME` and
`GHCR_TOKEN`.

Persistent files are stored under `/opt/sal-resource-manager`. Back up and
restore `data/sal_resources.db` when replacing a host; deployment does not copy
application data. Provider firewalls must allow inbound TCP ports `8443` and
`3000`.

Re-run the command after configuration or public-IP changes and periodically
to renew the webhook certificate.
