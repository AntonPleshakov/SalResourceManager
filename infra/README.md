# Server configuration

`configure-server.py` describes the current desired state of a Sal Resources
Manager host. It is intentionally updated in place and may be run repeatedly
against a new or existing server. Git provides the change history; this
directory is not an append-only migration log.

The thin `configure-server.py` entry point delegates argument parsing and SSH
orchestration to the `configure_server` Python package. Linux operations live
in the separate `configure_server/remote.sh` script. It is copied to the
temporary directory on the server and executed with Bash, so Python is not
required on the remote host.

The script ensures that:

- Docker Engine is available and the Compose plugin is installed;
- `/opt/sal-resource-manager`, `config/`, and `data/` exist;
- `data/` is owned by UID/GID `10001`;
- the current `compose.yaml`, application config, and Google report credentials
  are installed with the required permissions;
- the configured application image is pulled and Compose is applied;
- the bot starts successfully and `/app/data` is a writable persistent mount.

This mount stores `sal_resources.db`. The file is application state and is not
managed or replaced by the server configuration script.

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
