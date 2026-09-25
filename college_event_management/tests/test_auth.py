from app import create_app
from app.models import User, db
from app.controllers.auth import get_dashboard_route_for_role


def setup_app():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'WTF_CSRF_ENABLED': False})
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name='Admin User', email='admin@example.com', password_hash='hashed', role='admin')
        db.session.add(user)
        db.session.commit()
    return app


def test_role_redirect_mapping():
    assert get_dashboard_route_for_role('admin') == '/admin/dashboard'
    assert get_dashboard_route_for_role('hod') == '/hod/dashboard'
    assert get_dashboard_route_for_role('organizer') == '/organizer/dashboard'
    assert get_dashboard_route_for_role('student') == '/student/dashboard'


def test_role_required_works_for_unauthorized_access():
    app = setup_app()
    client = app.test_client()
    response = client.get('/admin/dashboard', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
