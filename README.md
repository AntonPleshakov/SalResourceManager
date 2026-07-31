# Sal Resources Manager

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
3. Copy the configuration template and fill it in:
   ```bash
   copy config\config_template.ini config\config.ini
   ```
4. Place the Google service account key at the project root as
   `gapi_service_file.json`.

## Run

```bash
MODE=Release python main.py
```

Available modes: `Release`, `Debug` (default), and `Test`.
