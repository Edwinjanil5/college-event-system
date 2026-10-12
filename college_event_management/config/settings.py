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

    # ------------------------------------------------------------------
    # Campus reference geolocation (constant)
    # Coordinates supplied by the college. These anchor every distance
    # calculation; they do not by themselves define the campus boundary.
    # ------------------------------------------------------------------
    CAMPUS_NAME = os.getenv('CAMPUS_NAME', 'College of Applied Sciences, Adoor (IHRD)')
    CAMPUS_ADDRESS = os.getenv(
        'CAMPUS_ADDRESS',
        'Hospital, Link Road, Parass La, Adoor, Kerala, India - 691523',
    )
    CAMPUS_LATITUDE = float(os.getenv('CAMPUS_LATITUDE', '9.1557'))
    CAMPUS_LONGITUDE = float(os.getenv('CAMPUS_LONGITUDE', '76.7369'))
    CAMPUS_RADIUS_M = float(os.getenv('CAMPUS_RADIUS_M', '250'))

    # Optional verified campus boundary (GeoJSON Polygon). When this file
    # exists and parses, the polygon replaces the circular-radius check.
    CAMPUS_POLYGON_FILE = os.getenv('CAMPUS_POLYGON_FILE') or ''

    # A GPS reading coarser than this cannot support a conclusive verdict.
    GPS_MAX_RELIABLE_ACCURACY_M = float(os.getenv('GPS_MAX_RELIABLE_ACCURACY_M', '100'))

    # Starting similarity threshold for the visual comparison. This is NOT a
    # validated decision boundary: it is an indicative cut-off that a
    # deployment should calibrate against real campus photographs.
    IMAGE_SIMILARITY_THRESHOLD = float(os.getenv('IMAGE_SIMILARITY_THRESHOLD', '0.92'))
    REFERENCE_IMAGE_FOLDER = os.getenv(
        'REFERENCE_IMAGE_FOLDER'
    ) or os.path.join(BASE_DIR, 'reference_images')
    REFERENCE_IMAGE_CACHE_FILE = os.getenv(
        'REFERENCE_IMAGE_CACHE_FILE'
    ) or os.path.join(_writable_folder('data'), 'reference_embeddings.json')
    # 'perceptual' (default, Pillow only) or 'clip' (optional PyTorch backend).
    IMAGE_EMBEDDING_BACKEND = os.getenv('IMAGE_EMBEDDING_BACKEND', 'perceptual')
    MAX_REFERENCE_IMAGE_BYTES = int(
        os.getenv('MAX_REFERENCE_IMAGE_BYTES', str(10 * 1024 * 1024))
    )

    # Location data is sensitive: records and their photos expire.
    VERIFICATION_RETENTION_DAYS = int(os.getenv('VERIFICATION_RETENTION_DAYS', '180'))

    MAX_VERIFICATION_IMAGE_BYTES = int(
        os.getenv('MAX_VERIFICATION_IMAGE_BYTES', str(400 * 1024))
    )
    ATTENDANCE_FOLDER = (
        os.getenv('ATTENDANCE_FOLDER') or _writable_folder(os.path.join('uploads', 'attendance'))
    )
