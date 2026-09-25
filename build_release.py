"""Build and smoke-check one clean CampusPulse Windows release."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / 'college_event_management'
VENV = PROJECT / 'venv'


def executable(name):
    if os.name == 'nt':
        return VENV / 'Scripts' / f'{name}.exe'
    return VENV / 'bin' / name


def run(command, cwd=PROJECT, env=None):
    print('>', ' '.join(map(str, command)), flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description='Build the CampusPulse release executable.')
    parser.add_argument('--skip-tests', action='store_true', help='Skip the test suite before building.')
    args = parser.parse_args()

    python = executable('python')
    if not python.exists():
        raise SystemExit('The project virtual environment is missing. Run setup_project.py --install first.')
    if not args.skip_tests:
        run([python, '-m', 'pytest', '-q'])
    run([executable('pyinstaller'), '--clean', '--noconfirm', 'CampusPulse.spec'])
    built = PROJECT / 'dist' / 'CampusPulse.exe'
    if not built.exists():
        raise SystemExit('PyInstaller completed without producing dist/CampusPulse.exe.')

    with tempfile.TemporaryDirectory(prefix='campuspulse-release-') as temp_dir:
        clean_db = Path(temp_dir) / 'college_event.db'
        environment = os.environ.copy()
        environment['FLASK_SKIP_DOTENV'] = '1'
        environment['CAMPUSPULSE_DATABASE_URL'] = f"sqlite:///{clean_db.as_posix()}"
        run([python, '-m', 'flask', '--app', 'run.py', 'db', 'upgrade'], env=environment)
        shutil.copy2(clean_db, PROJECT / 'dist' / 'college_event.db')

    print(f'Ready: {built}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
