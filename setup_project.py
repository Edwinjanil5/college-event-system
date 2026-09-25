"""Safe CampusPulse project helper.

This script never overwrites application source files. It only installs
declared dependencies and runs explicit maintenance commands.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
APP_ROOT = ROOT / 'college_event_management'
VENV_ROOT = APP_ROOT / 'venv'


def python_executable():
    if os.name == 'nt':
        candidate = VENV_ROOT / 'Scripts' / 'python.exe'
    else:
        candidate = VENV_ROOT / 'bin' / 'python'
    return candidate if candidate.exists() else Path(sys.executable)


def run_python(arguments, **kwargs):
    command = [str(python_executable()), *map(str, arguments)]
    environment = os.environ.copy()
    # Flask's CLI otherwise searches parent directories for an unrelated .env
    # file. CampusPulse should use this project's configuration only.
    environment.setdefault('FLASK_SKIP_DOTENV', '1')
    if not (
        environment.get('CAMPUSPULSE_DATABASE_URL')
        or environment.get('DATABASE_URL')
        or environment.get('LOCAL_DATABASE_URL')
    ):
        environment['CAMPUSPULSE_DATABASE_URL'] = 'sqlite:///' + str(APP_ROOT / 'college_event.db')
    print('>', ' '.join(command))
    return subprocess.run(command, cwd=APP_ROOT, env=environment, check=True, **kwargs).returncode


def database_has_legacy_sqlite_tables():
    database = APP_ROOT / 'college_event.db'
    if not database.exists():
        return False
    try:
        import sqlite3

        with sqlite3.connect(database) as connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            version = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            return bool(table and not version)
    except sqlite3.Error:
        return False


def main():
    parser = argparse.ArgumentParser(description='Safely prepare or run CampusPulse.')
    parser.add_argument('--install', action='store_true', help='Install pinned Python dependencies.')
    parser.add_argument('--migrate', action='store_true', help='Apply Alembic database migrations.')
    parser.add_argument('--create-admin', action='store_true', help='Interactively provision the first administrator.')
    parser.add_argument('--reset-admin-password', action='store_true', help='Interactively reset an administrator password.')
    parser.add_argument('--create-hod', action='store_true', help='Interactively provision a HoD account.')
    parser.add_argument('--reset-hod-password', action='store_true', help='Interactively reset a HoD password.')
    parser.add_argument('--test', action='store_true', help='Run the test suite.')
    parser.add_argument('--run', action='store_true', help='Start the local application.')
    parser.add_argument('--browser', action='store_true', help='Use browser mode with --run.')
    parser.add_argument('--port', type=int, help='Port for browser mode (default: 5000).')
    args = parser.parse_args()

    if not any((args.install, args.migrate, args.create_admin, args.reset_admin_password, args.create_hod, args.reset_hod_password, args.test, args.run)):
        parser.print_help()
        print('\nTypical first run:')
        print('  python setup_project.py --install --migrate')
        print('  python setup_project.py --create-admin')
        print('  python setup_project.py --create-hod')
        print('  python setup_project.py --run --browser')
        return 0

    if args.install:
        run_python(['-m', 'pip', 'install', '-r', 'requirements.txt'])

    if args.migrate:
        if database_has_legacy_sqlite_tables():
            print('Detected a legacy SQLite database; stamping the reviewed baseline before upgrading.')
            run_python(['-m', 'flask', '--app', 'run.py', 'db', 'stamp', 'c4fdc919364a'])
        run_python(['-m', 'flask', '--app', 'run.py', 'db', 'upgrade'])

    if args.create_admin:
        run_python(['-m', 'flask', '--app', 'run.py', 'create-admin'])

    if args.reset_admin_password:
        run_python(['-m', 'flask', '--app', 'run.py', 'reset-admin-password'])

    if args.create_hod:
        run_python(['-m', 'flask', '--app', 'run.py', 'create-hod'])

    if args.reset_hod_password:
        run_python(['-m', 'flask', '--app', 'run.py', 'reset-hod-password'])

    if args.test:
        run_python(['-m', 'pytest'])

    if args.run:
        environment = os.environ.copy()
        environment.setdefault('FLASK_SKIP_DOTENV', '1')
        if not (
            environment.get('CAMPUSPULSE_DATABASE_URL')
            or environment.get('DATABASE_URL')
            or environment.get('LOCAL_DATABASE_URL')
        ):
            environment['CAMPUSPULSE_DATABASE_URL'] = 'sqlite:///' + str(APP_ROOT / 'college_event.db')
        if args.browser:
            environment['CAMPUSPULSE_BROWSER'] = '1'
        if args.port:
            environment['CAMPUSPULSE_PORT'] = str(args.port)
        command = [str(python_executable()), 'run.py']
        print('>', ' '.join(command))
        return subprocess.run(command, cwd=APP_ROOT, env=environment, check=False).returncode

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
