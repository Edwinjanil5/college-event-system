from datetime import datetime

from app import create_app
from app.controllers.admin import calculate_pa_points
from app.models import Event, Registration, User, db


def test_pa_point_calculation_algorithm():
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'WTF_CSRF_ENABLED': False})
    with app.app_context():
        db.drop_all()
        db.create_all()
        organizer = User(name='Organizer', email='organizer@example.com', password_hash='hashed', role='organizer')
        db.session.add(organizer)
        db.session.commit()

        event = Event(
            title='Tech Summit',
            description='Sample event',
            venue='Main Hall',
            event_date=datetime(2027, 1, 20),
            registration_deadline=datetime(2027, 1, 18),
            max_participants=100,
            is_intercollege=True,
            organizer_id=organizer.id,
            status='approved',
        )
        db.session.add(event)
        db.session.commit()

        for i in range(55):
            user = User(name=f'User {i}', email=f'user{i}@example.com', password_hash='hashed', role='student')
            db.session.add(user)
            db.session.flush()
            db.session.add(Registration(user_id=user.id, event_id=event.id))

        db.session.commit()

        result = calculate_pa_points(event)
        assert result['base'] == 10
        assert result['bonus_participants'] == 2
        assert result['bonus_intercollege'] == 5
        assert result['total'] == 17
