# Server configuration

`configure-server.py` describes the current desired state of a Sal Resources
Manager host. It is intentionally updated in place and may be run repeatedly
against a new or existing server. Git provides the change history; this
directory is not an append-only migration log.

The thin `configure-server.py` entry point delegates argument parsing and SSH
orchestration to the `configure_server` Python package. Linux operations live
in the separate `configure_server/remote.sh` script. The certificate lifecycle
is implemented by `configure_server/generate-webhook-certificate.sh`. Both are
copied to the temporary directory on the server and executed with Bash, so
Python is not required on the remote host.

The script ensures that:

- Docker Engine is available and the Compose plugin is installed;
- `/opt/sal-resource-manager`, `config/`, `certs/`, and `data/` exist;
- `data/` is owned by UID/GID `10001`;
- OpenSSL is installed and a self-signed webhook certificate matching the
  public IPv4 address in `WEBHOOK_URL` exists;
- active UFW installations allow inbound TCP port `8443`;
- the current `compose.yaml`, Prometheus config, application config, and Google
  report credentials are installed with the required permissions;
- the configured application image is pulled and Compose is applied;
- the bot starts successfully and `/app/data` is a writable persistent mount.

The data mount stores `sal_resources.db`. The certificate mount stores the
generated public certificate and private key. Both survive container and image
replacement.

Docker Engine itself must already be installed. The SSH user must be `root` or
have passwordless `sudo` access.

## SSH config alias

The recommended setup is to keep connection details in `~/.ssh/config`:

```sshconfig
Host sal-production
    HostName example.com
    User deploy
    Port 2222
    IdentityFile ~/.ssh/sal_resource_manager
```

Then configure either a new or an existing host with:

```bash
python infra/configure-server.py sal-production
```

When `-i` and `-p` are omitted, OpenSSH resolves the identity, port, user,
`ProxyJump`, and other settings from the SSH configuration.

Explicit overrides are also supported:

```bash
python infra/configure-server.py \
  -i ~/.ssh/sal_resource_manager \
  -p 2222 \
  user@server
```

Options and environment variables:

- `-c path` or `CONFIG_FILE` — application config;
- `-g path` or `GOOGLE_CREDENTIALS_FILE` — report service-account file;
- `-i path` or `SSH_IDENTITY_FILE` — SSH identity override;
- `-p port` or `SSH_PORT` — SSH port override;
- `SSH_TARGET` — target when the positional argument is omitted;
- `GHCR_USERNAME` and `GHCR_TOKEN` — optional registry login credentials.

If registry credentials are omitted, the script uses the Docker login already
present on the server. Both variables must be supplied together when a login is
required.

## Repeated runs and host replacement

The script compares managed files before replacing them and relies on
`docker compose up` to reconcile the container. It forces recreation when the
mounted application config or report credentials change.

To prepare a replacement host, add its SSH alias and run the same command. The
SQLite database is application state and is not copied by this script. A
replacement host requires a controlled backup and restore of
`sal_resources.db` before the bot is started. An empty database receives the
schema but contains no administrators or user data. War stages are hardcoded in
the application and do not need to be restored.

Automatic GitHub deployments continue to update only the application image.
Host directories, permissions, Compose configuration, and secrets are managed
by `configure-server.py`.

Prometheus stores its time series in the `prometheus-data` Docker volume and is
available only on the server loopback interface at `http://127.0.0.1:9090`.
Use an SSH tunnel when remote access to its web UI is needed.

## Webhook certificate

Set the following values before configuring the server:

```ini
WEBHOOK_URL = https://203.0.113.10:8443/telegram/
```

Replace `203.0.113.10` with the server's static public IPv4 address. The
listener address, port, certificate paths, and webhook secret are managed by
application defaults and do not require deployment-specific configuration. The
certificate generator validates the address, creates a 2048-bit RSA certificate
whose CN and subject alternative name match it, and protects the private key
with mode `0400`. Existing certificates are retained until they have fewer than
30 days remaining. Re-run `configure-server.py` periodically to renew the
certificate and after changing the server's public IP.

The script can also be run directly on the server as root:

```bash
sudo /opt/sal-resource-manager/generate-webhook-certificate.sh \
  203.0.113.10 \
  /opt/sal-resource-manager/certs/webhook.pem \
  /opt/sal-resource-manager/certs/webhook.key \
  10001 10001
```

If it prints `generated`, restart the bot so it loads and uploads the new
certificate. Provider-level firewalls are outside the script's control and
must allow inbound TCP port `8443`.
