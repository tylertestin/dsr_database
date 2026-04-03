# DSR Database Tool

A Flask-based web app for loading and exploring vehicle status history stored in SQLite.

## What this tool does

- Loads and analyzes vehicle status records backed by `vehicle_data.db`.
- Displays dashboard-style summaries and status breakdowns in the browser.
- Supports importing Excel report data into the database.

## Prerequisites

- **Python 3.10+** (3.11 recommended)
- `pip`
- Access to your project files (including `templates/` and `static/`)

## 1) Install

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> On Windows PowerShell, activate with:
> `\.venv\Scripts\Activate.ps1`

## 2) Prepare data

The app expects an SQLite file named:

- `vehicle_data.db`

By default, the app reads this file from the project root. If it does not exist yet, place your database there before launching.

## 3) Run the app

### Option A (recommended): launch with browser auto-open

```bash
python run_app.py
```

This starts Flask on `http://127.0.0.1:5000` and opens your browser automatically.

### Option B: run Flask app directly

```bash
python app.py
```

Then manually open:

- `http://127.0.0.1:5000`

## 4) Using the app

- Open the home page and choose available site filters.
- Use the provided pages to inspect PM trends, fleet views, and custom SQL views.
- For custom SQL, keep quoted column names where needed (for example identifiers with spaces).

## Optional: build a standalone executable

A PyInstaller spec is included:

```bash
pip install pyinstaller
pyinstaller run_app.spec
```

The built executable output is written to `dist/` (or your configured build output path).

## Troubleshooting

- **`ModuleNotFoundError`**: confirm your virtual environment is activated and `pip install -r requirements.txt` completed.
- **Port already in use**: stop the other process using port `5000`, or update the host/port in `run_app.py`.
- **No data appears**: verify `vehicle_data.db` exists in the project root and contains expected tables.
- **Charts/templates not loading**: run from the repository root so Flask can locate `templates/` and `static/`.

## Project layout (quick reference)

- `app.py` – main Flask application and routes
- `run_app.py` – convenience launcher (starts app + opens browser)
- `scripts/DSR_funcs.py` – helper functions for Excel import and status-history processing
- `templates/` – HTML templates
- `static/` – CSS/images
- `requirements.txt` – Python dependencies
