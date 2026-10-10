import os
import secrets
import sys
import tempfile
from datetime import timedelta

from dotenv import load_dotenv

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(BASE_DIR, '.env'))

DEFAULT_MYSQL_URI = 'mysql+pymysql://root:root@localhost:3306/college_event_db'


def _database_uri():
    value = (
        os.getenv('CAMPUSPULSE_DATABASE_URL')
        or os.getenv('DATABASE_URL')
        or os.getenv('LOCAL_DATABASE_URL')
        or 'sqlite:///' + os.path.join(BASE_DIR, 'college_event.db')
    )
    if value.startswith('sqlite:///') and not value.startswith('sqlite:////'):
        relative_path = value[len('sqlite:///'):]
        if relative_path and relative_path != ':memory:' and not os.path.isabs(relative_path):
            value = 'sqlite:///' + os.path.join(BASE_DIR, relative_path)
    return value


def _writable_folder(preferred_name):
    """Return ``preferred_name`` when it is writable, else a temp folder.

    Serverless deployments ship a read-only project directory, so the trained
    model cache has to fall back to a writable location.
    """
    preferred = os.path.join(BASE_DIR, preferred_name)
    try:
        os.makedirs(preferred, exist_ok=True)
        probe = os.path.join(preferred, '.write-probe')
        with open(probe, 'w', encoding='utf-8') as handle:
            handle.write('ok')
        os.remove(probe)
        return preferred
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), 'campuspulse')
        os.makedirs(fallback, exist_ok=True)
        return fallback


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REPORTS_FOLDER = os.getenv('REPORTS_FOLDER') or os.path.join(BASE_DIR, 'static', 'uploads')
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0') == '1'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0') == '1'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = int(os.getenv('WTF_CSRF_TIME_LIMIT', '3600'))
    AUTO_CREATE_DB = os.getenv(
        'AUTO_CREATE_DB',
        '1' if getattr(sys, 'frozen', False) else '0',
    ) == '1'
    REPORT_RETENTION_DAYS = int(os.getenv('REPORT_RETENTION_DAYS', '30'))
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH', str(2 * 1024 * 1024)))
    MAX_REPORT_FILES = int(os.getenv('MAX_REPORT_FILES', '100'))
    SUPPORT_NAME = os.getenv('SUPPORT_NAME', 'Edwin J Anil')
    SUPPORT_ROLE = os.getenv('SUPPORT_ROLE', 'Developer')
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL', 'edwinjanil5@gmail.com')
    SUPPORT_PHONE = os.getenv('SUPPORT_PHONE', '8138815144')
    GOOGLE_SITE_VERIFICATION = os.getenv('GOOGLE_SITE_VERIFICATION', '')

    # Constant reference geolocation used by the geolocation cross-match model.
    CAMPUS_NAME = os.getenv('CAMPUS_NAME', 'College of Applied Science, Adoor')
    CAMPUS_ADDRESS = os.getenv(
        'CAMPUS_ADDRESS',
        'Parthasarathy Road, Kannamkode, Adoor, Pathanamthitta, Kerala 691523',
    )
    CAMPUS_LATITUDE = float(os.getenv('CAMPUS_LATITUDE', '9.1553906'))
    CAMPUS_LONGITUDE = float(os.getenv('CAMPUS_LONGITUDE', '76.7310322'))
    CAMPUS_RADIUS_M = float(os.getenv('CAMPUS_RADIUS_M', '250'))
    GEO_MATCH_THRESHOLD = float(os.getenv('GEO_MATCH_THRESHOLD', '0.5'))
    GEO_MODEL_FOLDER = os.getenv('GEO_MODEL_FOLDER') or _writable_folder('data')
    MAX_VERIFICATION_IMAGE_BYTES = int(
        os.getenv('MAX_VERIFICATION_IMAGE_BYTES', str(400 * 1024))
    )
    ATTENDANCE_FOLDER = (
        os.getenv('ATTENDANCE_FOLDER') or _writable_folder(os.path.join('uploads', 'attendance'))
    )
