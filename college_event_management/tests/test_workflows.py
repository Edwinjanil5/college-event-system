from datetime import timedelta

from app.models import Event, Feedback, Registration, User, db
from app.workflow import utcnow


def login(client, email, password='password123'):
    return client.post('/login', data={'email': email, 'password': password})


def test_organizer_can_select_class_incharge_status(client, app, user_factory):
    with app.app_context():
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add(organizer)
        db.session.commit()
        organizer_id = organizer.id

    login(client, 'organizer@example.com')
    dashboard = client.get('/organizer/dashboard')
    assert dashboard.status_code == 200
    assert b'class_incharge_status' in dashboard.data

    response = client.post(
        '/organizer/profile/class-incharge',
        data={'class_incharge_status': 'yes'},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, organizer_id).is_class_incharge is True

    client.post(
        '/organizer/profile/class-incharge',
        data={'class_incharge_status': 'no'},
    )
    with app.app_context():
        assert db.session.get(User, organizer_id).is_class_incharge is False


def test_hod_verifies_program_before_admin_final_approval(client, app, user_factory):
    with app.app_context():
        organizer = user_factory('organizer', 'organizer@example.com')
        hod = user_factory('hod', 'hod@example.com', name='Head of Department')
        admin = user_factory('admin', 'admin@example.com')
        db.session.add_all([organizer, hod, admin])
        db.session.commit()
        event = Event(
            title='Department program',
            venue='Auditorium',
            event_date=utcnow() + timedelta(days=3),
            registration_deadline=utcnow() + timedelta(days=2),
            max_participants=100,
            organizer_id=organizer.id,
            status='pending_hod',
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    hod_client = app.test_client()
    login(hod_client, 'hod@example.com')
    assert hod_client.get('/hod/dashboard').status_code == 200
    response = hod_client.post(
        f'/hod/events/{event_id}/review',
        data={'action': 'send_to_admin'},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Event, event_id).status == 'hod_approved'

    admin_client = app.test_client()
    login(admin_client, 'admin@example.com')
    response = admin_client.post(
        f'/admin/events/{event_id}/review',
        data={'action': 'approve'},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Event, event_id).status == 'approved'


def test_admin_cannot_final_approve_before_hod_verification(client, app, user_factory):
    with app.app_context():
        organizer = user_factory('organizer', 'organizer@example.com')
        admin = user_factory('admin', 'admin@example.com')
        db.session.add_all([organizer, admin])
        db.session.commit()
        event = Event(
            title='Unverified program',
            venue='Auditorium',
            event_date=utcnow() + timedelta(days=3),
            registration_deadline=utcnow() + timedelta(days=2),
            max_participants=50,
            organizer_id=organizer.id,
            status='pending_hod',
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    login(client, 'admin@example.com')
    client.post(f'/admin/events/{event_id}/review', data={'action': 'approve'})
    with app.app_context():
        assert db.session.get(Event, event_id).status == 'pending_hod'


def test_organizer_rejects_invalid_event_dates_and_capacity(client, app, user_factory):
    with app.app_context():
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add(organizer)
        db.session.commit()

    login(client, 'organizer@example.com')
    response = client.post(
        '/organizer/events/new',
        data={
            'title': 'Invalid event',
            'venue': 'Hall',
            'event_date': '2030-01-01T10:00',
            'registration_deadline': '2030-01-02T10:00',
            'max_participants': 'not-a-number',
            'fee_type': 'free',
            'ticket_fee': '0',
        },
    )
    assert response.status_code == 200
    with app.app_context():
        assert Event.query.filter_by(title='Invalid event').count() == 0


def test_organizer_cannot_complete_unapproved_or_future_event(client, app, user_factory):
    with app.app_context():
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add(organizer)
        db.session.commit()
        now = utcnow()
        pending = Event(
            title='Pending event',
            venue='Hall',
            event_date=now + timedelta(days=2),
            registration_deadline=now + timedelta(days=1),
            max_participants=20,
            organizer_id=organizer.id,
            status='pending_hod',
        )
        future = Event(
            title='Future event',
            venue='Hall',
            event_date=now + timedelta(days=2),
            registration_deadline=now + timedelta(days=1),
            max_participants=20,
            organizer_id=organizer.id,
            status='approved',
        )
        db.session.add_all([pending, future])
        db.session.commit()
        pending_id = pending.id
        future_id = future.id

    login(client, 'organizer@example.com')
    client.post(f'/organizer/events/{pending_id}/complete')
    client.post(f'/organizer/events/{future_id}/complete')

    with app.app_context():
        assert db.session.get(Event, pending_id).status == 'pending_hod'
        assert db.session.get(Event, future_id).status == 'approved'


def test_admin_can_only_review_pending_events(client, app, user_factory):
    with app.app_context():
        admin = user_factory('admin', 'admin@example.com')
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add_all([admin, organizer])
        db.session.commit()
        event = Event(
            title='Already approved',
            venue='Hall',
            event_date=utcnow() + timedelta(days=2),
            registration_deadline=utcnow() + timedelta(days=1),
            max_participants=20,
            organizer_id=organizer.id,
            status='approved',
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    login(client, 'admin@example.com')
    client.post(f'/admin/events/{event_id}/review', data={'action': 'reject'})

    with app.app_context():
        assert db.session.get(Event, event_id).status == 'approved'


def test_feedback_requires_registration_and_only_one_submission(client, app, user_factory):
    with app.app_context():
        student = user_factory('student', 'student@example.com')
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add_all([student, organizer])
        db.session.commit()
        event = Event(
            title='Completed event',
            venue='Hall',
            event_date=utcnow() - timedelta(days=1),
            registration_deadline=utcnow() - timedelta(days=2),
            max_participants=20,
            organizer_id=organizer.id,
            status='completed',
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id
        student_id = student.id

    login(client, 'student@example.com')
    client.post(f'/student/events/{event_id}/feedback', data={'rating': '5', 'comments': 'Great'})
    with app.app_context():
        assert Feedback.query.filter_by(event_id=event_id, user_id=student_id).count() == 0

        db.session.add(Registration(user_id=student_id, event_id=event_id))
        db.session.commit()

    response = client.post(
        f'/student/events/{event_id}/feedback',
        data={'rating': '5', 'comments': 'Great event'},
    )
    assert response.status_code == 302
    with app.app_context():
        assert Feedback.query.filter_by(event_id=event_id, user_id=student_id).count() == 1

    client.post(f'/student/events/{event_id}/feedback', data={'rating': '4'})
    with app.app_context():
        assert Feedback.query.filter_by(event_id=event_id, user_id=student_id).count() == 1


def test_registration_capacity_and_payment_policy(client, app, user_factory):
    with app.app_context():
        first = user_factory('student', 'first@example.com')
        second = user_factory('student', 'second@example.com')
        organizer = user_factory('organizer', 'organizer@example.com')
        db.session.add_all([first, second, organizer])
        db.session.commit()
        event = Event(
            title='One seat',
            venue='Hall',
            event_date=utcnow() + timedelta(days=2),
            registration_deadline=utcnow() + timedelta(days=1),
            max_participants=1,
            ticket_fee=250,
            organizer_id=organizer.id,
            status='approved',
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    first_client = app.test_client()
    second_client = app.test_client()
    login(first_client, 'first@example.com')
    login(second_client, 'second@example.com')
    assert first_client.post(f'/student/events/{event_id}/register').status_code == 302
    assert second_client.post(f'/student/events/{event_id}/register').status_code == 302

    payment_response = first_client.get(f'/student/events/{event_id}/payment-info')
    assert payment_response.status_code == 302
    assert payment_response.headers['Location'].endswith('/student/dashboard')
    with app.app_context():
        assert Registration.query.filter_by(event_id=event_id).count() == 1
