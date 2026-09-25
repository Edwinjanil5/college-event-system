import re

from flask_bcrypt import generate_password_hash

from app import create_app
from app.models import User, db


def test_support_page_exposes_developer_contact_details(client):
    response = client.get('/contact')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Edwin J Anil' in body
    assert 'edwinjanil5@gmail.com' in body
    assert '8138815144' in body
    assert 'mailto:edwinjanil5@gmail.com' in body
    assert 'tel:8138815144' in body


def test_security_headers_and_local_assets_are_served(client, app):
    response = client.get('/')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert 'Content-Security-Policy' in response.headers
    assert client.get('/static/vendor/bootstrap/bootstrap.min.css').status_code == 200
    assert client.get('/static/vendor/bootstrap/bootstrap.bundle.min.js').status_code == 200
    assert client.get('/static/images/campuspulse-logo.png').status_code == 200


def test_public_pages_use_the_campus_theme_shell(client):
    response = client.get('/login')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'campuspulse-page' in body
    assert 'campuspulse-navbar' in body
    assert 'campuspulse-main' in body


def test_public_registration_rejects_admin_role_and_hashes_password(client, app, user_factory):
    response = client.post(
        '/register',
        data={
            'name': 'Student One',
            'email': 'student@example.com',
            'password': 'password123',
            'role': 'admin',
        },
    )

    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email='student@example.com').first() is None


def test_public_registration_rejects_hod_role(client, app):
    response = client.post(
        '/register',
        data={
            'name': 'Unverified HoD',
            'email': 'unverified-hod@example.com',
            'password': 'password123',
            'role': 'hod',
        },
    )
    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email='unverified-hod@example.com').first() is None


def test_admin_can_create_hod_account_from_admin_dashboard(client, app, user_factory):
    with app.app_context():
        admin = user_factory('admin', 'admin@example.com')
        db.session.add(admin)
        db.session.commit()

    login_response = client.post(
        '/login',
        data={'email': 'admin@example.com', 'password': 'password123'},
    )
    assert login_response.status_code == 302
    assert client.get('/admin/hod/create').status_code == 200

    response = client.post(
        '/admin/hod/create',
        data={
            'name': 'Department Head',
            'email': 'department-head@example.com',
            'password': 'a-long-secure-password',
            'password_confirmation': 'a-long-secure-password',
        },
    )
    assert response.status_code == 302
    with app.app_context():
        hod = User.query.filter_by(email='department-head@example.com').first()
        assert hod is not None
        assert hod.role == 'hod'
        assert hod.password_hash != 'a-long-secure-password'


def test_admin_login_uses_stored_bcrypt_hash(client, app, user_factory):
    with app.app_context():
        admin = user_factory('admin', 'admin@example.com', password='correct-horse-battery')
        db.session.add(admin)
        db.session.commit()

    response = client.post(
        '/admin/login',
        data={'email': 'admin@example.com', 'password': 'correct-horse-battery'},
    )
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin/dashboard')


def test_admin_login_does_not_create_default_account(client, app):
    legacy_email = 'former-admin@example.com'
    response = client.post(
        '/admin/login',
        data={'email': legacy_email, 'password': 'legacy-password'},
    )
    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email=legacy_email).first() is None


def test_admin_cli_provisions_without_a_default_password(app):
    result = app.test_cli_runner().invoke(
        args=[
            'create-admin',
            '--email',
            'provisioned@example.com',
            '--name',
            'Provisioned Admin',
            '--password',
            'a-long-development-password',
        ]
    )
    assert result.exit_code == 0
    with app.app_context():
        admin = User.query.filter_by(email='provisioned@example.com').first()
        assert admin is not None
        assert admin.role == 'admin'
        assert admin.password_hash != 'a-long-development-password'


def test_logout_requires_post(client, app, user_factory):
    with app.app_context():
        user = user_factory('student', 'student@example.com')
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client.post('/login', data={'email': 'student@example.com', 'password': 'password123'})
    assert client.get('/logout').status_code == 405
    response = client.post('/logout')
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, user_id) is not None


def test_csrf_is_enforced_for_post_requests():
    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'WTF_CSRF_ENABLED': True,
        }
    )
    with app.app_context():
        db.create_all()
    client = app.test_client()
    html = client.get('/login').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    assert client.post('/login', data={'email': 'nobody@example.com', 'password': 'x'}).status_code == 400
    response = client.post(
        '/login',
        data={
            'email': 'nobody@example.com',
            'password': 'x',
            'csrf_token': token,
        },
    )
    assert response.status_code == 200
