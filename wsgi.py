"""Vercel WSGI entry point for CampusPulse.

Vercel imports the top-level ``app`` object from this file. The application
source remains in ``college_event_management`` so the local desktop build and
the hosted test share the same Flask code.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_ROOT = ROOT / "college_event_management"

# The application uses top-level ``app`` and ``config`` imports internally.
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Safe, disposable defaults for a Vercel test. Set real values as Vercel
# environment variables before using this outside a temporary test.
os.environ.setdefault("CAMPUSPULSE_BROWSER", "1")
os.environ.setdefault("AUTO_CREATE_DB", "1")
os.environ.setdefault("CAMPUSPULSE_DATABASE_URL", "sqlite:////tmp/campuspulse-vercel.db")
os.environ.setdefault("REPORTS_FOLDER", "/tmp/reports")
os.environ.setdefault("SESSION_COOKIE_SECURE", "1")

from app import create_app  # noqa: E402  (path setup must happen first)

app = create_app()
