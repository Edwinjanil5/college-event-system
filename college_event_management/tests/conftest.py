import pytest
from flask_bcrypt import generate_password_hash

from app import create_app
from app.models import User, db


# bcrypt at its production cost dominates suite runtime; tests only need a
# real hash, not a slow one.
BCRYPT_ROUNDS = 4


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'WTF_CSRF_ENABLED': False,
            'BCRYPT_LOG_ROUNDS': BCRYPT_ROUNDS,
            'REPORTS_FOLDER': str(tmp_path / 'reports'),
            'REPORT_RETENTION_DAYS': 30,
            'MAX_REPORT_FILES': 20,
            'GEO_MODEL_FOLDER': str(tmp_path / 'geo-model'),
            'ATTENDANCE_FOLDER': str(tmp_path / 'attendance'),
            'REFERENCE_IMAGE_FOLDER': str(tmp_path / 'reference-images'),
            'REFERENCE_IMAGE_CACHE_FILE': str(tmp_path / 'reference-images-cache.json'),
            'IMAGE_EMBEDDING_BACKEND': 'perceptual',
            'CAMPUS_LATITUDE': 9.1557,
            'CAMPUS_LONGITUDE': 76.7369,
            'CAMPUS_RADIUS_M': 250.0,
            'GPS_MAX_RELIABLE_ACCURACY_M': 100.0,
            'IMAGE_SIMILARITY_THRESHOLD': 0.92,
            'VERIFICATION_RETENTION_DAYS': 180,
        }
    )
    with application.app_context():
        db.drop_all()
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user_factory():
    return make_user


def make_user(role, email, password='password123', name=None):
    return User(
        name=name or role.title(),
        email=email,
        # A low cost factor keeps the suite fast; production keeps the default.
        password_hash=generate_password_hash(password, rounds=BCRYPT_ROUNDS).decode('utf-8'),
        role=role,
    )
