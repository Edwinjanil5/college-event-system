# CampusPulse

CampusPulse is a Flask-based college event-management application with student, organizer, HoD, and administrator workflows. It runs as a local web application or a packaged Windows desktop application.

## Included workflows

- Student and organizer registration with bcrypt password hashing
- Organizer event submission and ownership checks
- Organizer profile flag for class-incharge status
- HoD verification stage before administrator approval
- Pending HoD → HoD approved → admin approved/rejected → completed event workflow
- Capacity/deadline-aware student registration and cancellation
- Feedback only for registered students and completed events
- PA point calculation and PDF/Excel report generation
- Real CSRF protection for state-changing requests
- CLI-based administrator provisioning; no default administrator password
- Local, versioned Alembic migrations
- Local Bootstrap assets for offline-friendly rendering
- CampusPulse website assistant for site-specific questions

## Requirements

- Python 3.11+ (the bundled environment currently uses Python 3.14)
- Windows for the packaged desktop build; the Flask application can run on other platforms
- SQLite by default; MySQL can be configured through `DATABASE_URL`

## First-time setup

From the repository root:

```powershell
Copy-Item college_event_management\.env.example college_event_management\.env
python setup_project.py --install --migrate
```

Edit `college_event_management/.env` and replace `SECRET_KEY` with a long random value before using the application beyond local development. `CAMPUSPULSE_DATABASE_URL` is preferred so an unrelated parent-directory `.env` cannot change the project database.

The setup helper is non-destructive: it never overwrites application source files.

## Create an administrator

There are no hard-coded administrator credentials. Provision the first administrator interactively from the repository root:

```powershell
python setup_project.py --create-admin
```

The command prompts for an email, name, and hidden password. To rotate an administrator password:

```powershell
python setup_project.py --reset-admin-password
```

Administrators then sign in through `/admin/login` using the account created by the CLI.

## Create a HoD account

HoD accounts are provisioned securely and cannot be self-registered. An administrator can use **Create HoD Account** on the Admin Dashboard, or use the CLI:

```powershell
python setup_project.py --create-hod
```

To rotate a HoD password:

```powershell
python setup_project.py --reset-hod-password
```

The HoD signs in through the normal login page and is redirected to `/hod/dashboard`.

## Run locally

From the repository root:

```powershell
python setup_project.py --run --browser
```

Or, from `college_event_management`:

```powershell
$env:CAMPUSPULSE_BROWSER = '1'
.\venv\Scripts\python.exe run.py
```

Set `CAMPUSPULSE_PORT` if port 5000 is unavailable. Without `CAMPUSPULSE_BROWSER=1`, the application opens in the `pywebview` desktop window.

## Database migrations

Migrations are in `college_event_management/migrations/`. Apply them with:

```powershell
python setup_project.py --migrate
```

The application does not silently alter an existing database at startup. `AUTO_CREATE_DB=1` is available only for isolated development/tests; normal releases should use migrations.

`schema.sql` is the reviewed MySQL reference schema. Keep it synchronized with the SQLAlchemy models when changing persistence.

## Tests

Tests use an isolated in-memory database and temporary report directory:

```powershell
python setup_project.py --test
```

Or:

```powershell
cd college_event_management
.\venv\Scripts\python.exe -m pytest -q
```

## Reports and payments

Reports are generated with a unique filename, escaped PDF text, literal Excel cells, and configurable retention limits. Report generation is a CSRF-protected POST action and is limited to completed events.

CampusPulse does **not** process or verify online payments. Paid-event fees are informational; registered students must contact the organizer for approved payment instructions and keep their receipt. This avoids presenting an unverified redirect as a completed payment.

## Build a clean Windows release

Build from the repository root after migrations and tests pass:

```powershell
python build_release.py
```

The helper runs the test suite and then builds `college_event_management/dist/CampusPulse.exe`. To run PyInstaller directly from the project directory:

```powershell
.\venv\Scripts\pyinstaller.exe --clean --noconfirm CampusPulse.spec
```

The executable is written to `dist/`. A frozen build creates a blank local database beside the executable on first run; keep that database with the release if you want to preserve data. Keep only one release executable and its matching database/configuration in a release directory. For an offline smoke test, launch a copy with:

```powershell
$env:CAMPUSPULSE_BROWSER = '1'
.\dist\CampusPulse.exe --browser
```

Then verify `/health`, the homepage, login, registration, and the assistant in a browser. Do not ship the development `college_event.db`, generated reports, `venv/`, or `build/` directories.

## Support contact

If the website or desktop app crashes, contact:

- **Edwin J Anil (Developer)**
- **Email:** edwinjanil5@gmail.com
- **Phone:** 8138815144

The same details appear in the website footer, the Support page at `/contact`, and the assistant's support response.

## Website assistant

The assistant is available from the floating **Ask CampusPulse** control on every page, including the homepage. Questions are answered by a server-side, website-specific knowledge layer at `/assistant/ask`; no API key is exposed to the browser. It can explain accounts, roles, event lifecycle, registrations, feedback, PA scoring, reports, security, local storage, and troubleshooting.

## Google Cloud reality test

For a safe hosted browser test, use the included Cloud Run + Cloud SQL MySQL deployment files. Do not deploy the local SQLite database to Cloud Run because its filesystem is ephemeral.

See [GOOGLE_CLOUD_DEPLOY.md](GOOGLE_CLOUD_DEPLOY.md) for the deployment, migration, secrets, and smoke-test checklist.
