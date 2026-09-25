import pytest
from flask_bcrypt import generate_password_hash

from app import create_app
from app.models import User, db


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'WTF_CSRF_ENABLED': False,
            'REPORTS_FOLDER': str(tmp_path / 'reports'),
            'REPORT_RETENTION_DAYS': 30,
            'MAX_REPORT_FILES': 20,
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
        password_hash=generate_password_hash(password).decode('utf-8'),
        role=role,
    )
