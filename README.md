# Station Monitor — Task 1: Base Layout, Theme & Config

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`.env` is already included for local dev with a placeholder `SECRET_KEY`.
For any real environment, copy `.env.example` to `.env` and set your own values.

## Run

```bash
python app.py
```

Visit http://localhost:5000

## What's included (Task 1 scope)

- Base HTML shell (`app/templates/base.html`) — header, nav, content block, footer
- Dark/light theme system — cookie-based, read server-side, no flash of wrong theme
- 4 nav routes (stub pages): Home, Live Kitting Activities, History, Configuration
- Active-page highlighting + hover states on nav buttons
- `config.yaml` (non-secret runtime config) + `.env` (secrets) merged via `app/config/loader.py`
- CSS split by concern: `reset.css`, `variables.css` (theme tokens), `layout.css`, `nav.css`
- Vanilla JS theme toggle in its own file: `app/static/js/theme-toggle.js`

## Not included yet (future tasks)

- Flask-SocketIO wiring
- MongoDB schema/connection
- Any business logic beyond placeholder pages

## Project structure

```
app/
├── blueprints/          # home, live_kitting_activities, history, configuration
├── templates/           # base.html + one folder per blueprint
├── static/css/          # reset, variables, layout, nav
├── static/js/           # theme-toggle.js
├── config/loader.py     # merges config.yaml + .env
config.yaml               # non-secret runtime config
.env / .env.example       # secrets
app.py                    # entry point
```
