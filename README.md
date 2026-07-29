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

## Run

```bash
MODE=Debug python main.py
```
