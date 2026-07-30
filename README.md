# Sal Resources Manager

## Quick setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Copy configuration template and fill in values:
   ```bash
   copy config\config_template.ini config\config.ini
   ```
4. Place the Google service account key at the project root as `gapi_service_file.json`.
5. Configure the admin sheet in Google Sheets with `Username` and `ID` columns.
6. Set `RESOURCES_GTABLE_KEY`. The bot creates the configured `Resources`
   worksheet and its columns automatically if it does not exist.

## Run

```bash
MODE=Debug python main.py
```

After the first message to the bot, all navigation and data editing are done
through inline buttons.
