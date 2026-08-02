# Server deployment

## Initial setup

Run the bootstrap script manually from the project directory:

```bash
./deploy/bootstrap-server.sh -i ~/.ssh/sal_resource_manager user@server
```

It copies the local `compose.yaml`, `config/config.ini`, and
`gapi_service_file.json`, then installs and starts the application remotely.
The server must have Docker Engine installed. The SSH user must be `root` or
have passwordless `sudo` access. The script securely prompts for a GHCR username
and token. For a private image, use a personal access token (classic) with the
`read:packages` scope.

Options:

- `-i identity_file`
- `-p port` (defaults to `22`)

Optional environment variables:

- `SSH_TARGET`
- `SSH_PORT`
- `SSH_IDENTITY_FILE`
- `CONFIG_FILE`
- `GOOGLE_CREDENTIALS_FILE`
- `GHCR_USERNAME` and `GHCR_TOKEN` to skip the interactive prompt

## Automatic updates

Pushes to `main` pull the latest image and restart the application. Configure
these GitHub Actions secrets:

- `DEPLOY_HOST`
- `DEPLOY_PORT` (optional, defaults to `22`)
- `DEPLOY_USER`
- `DEPLOY_SSH_PRIVATE_KEY`
- `DEPLOY_SSH_KNOWN_HOSTS`
