"""Tests for the camera + geolocation verification flow."""

import base64
from datetime import timedelta

from app.models import Event, GeoVerification, Registration, db
from app.workflow import utcnow


CAMPUS_LAT = 9.1553906
CAMPUS_LNG = 76.7310322


def login(client, email, password='password123'):
    return client.post('/login', data={'email': email, 'password': password})


def _jpeg_data_url():
    # Minimal JPEG header bytes; the controller only validates the magic bytes.
    raw = b'\xff\xd8\xff\xe0' + b'\x00' * 32
    return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')


def _setup(app, user_factory, *, approved=True, organizer_email='owner@example.com'):
    with app.app_context():
        student = user_factory('student', 'verify-student@example.com')
        organizer = user_factory('organizer', organizer_email)
        db.session.add_all([student, organizer])
        db.session.commit()
        event = Event(
            title='Verified event',
            venue='Hall',
            event_date=utcnow() + timedelta(days=1),
            registration_deadline=utcnow() + timedelta(days=2),
            max_participants=20,
            organizer_id=organizer.id,
            status='approved',
        )
        db.session.add(event)
        db.session.commit()
        db.session.add(
            Registration(
                user_id=student.id,
                event_id=event.id,
                status='approved' if approved else 'pending_teacher',
            )
        )
        db.session.commit()
        return event.id


def test_verification_page_requires_login_and_approved_registration(app, client, user_factory):
    event_id = _setup(app, user_factory, approved=False)

    anonymous = client.get(f'/verify/{event_id}')
    assert anonymous.status_code in (302, 401, 403)

    login(client, 'verify-student@example.com')
    response = client.get(f'/verify/{event_id}')
    assert response.status_code == 302, 'pending registration must not open the page'
    assert b'/student/dashboard' in response.headers['Location'].encode()


def test_student_can_cross_match_a_campus_location(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    page = client.get(f'/verify/{event_id}')
    assert page.status_code == 200
    assert b'College of Applied Science, Adoor' in page.data

    response = client.post(
        f'/verify/{event_id}/check',
        json={'latitude': CAMPUS_LAT, 'longitude': CAMPUS_LNG, 'accuracy': 12, 'source': 'device'},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['verdict'] == 'match'
    assert payload['matched'] is True
    assert payload['distance_m'] < 5
    assert payload['campus']['latitude'] == CAMPUS_LAT
    assert payload['model']['version']

    with app.app_context():
        record = GeoVerification.query.filter_by(event_id=event_id).one()
        assert record.verdict == 'match'
        assert record.source == 'device'
        assert record.user_id is not None


def test_distant_location_is_recorded_as_mismatch(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    response = client.post(
        f'/verify/{event_id}/check',
        json={'latitude': 8.5241, 'longitude': 76.9366, 'accuracy': 30},
    )
    payload = response.get_json()
    assert payload['verdict'] == 'mismatch'
    assert payload['distance_m'] > 10000


def test_random_shot_endpoint_returns_a_valid_point(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    response = client.post(f'/verify/{event_id}/random-shot', json={})
    assert response.status_code == 200
    payload = response.get_json()
    point = payload['point']
    assert -90.0 <= point['latitude'] <= 90.0
    assert -180.0 <= point['longitude'] <= 180.0
    assert isinstance(payload['simulated_inside_campus'], bool)
    assert payload['campus']['name'] == 'College of Applied Science, Adoor'


def test_invalid_payloads_are_rejected(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    missing = client.post(f'/verify/{event_id}/check', json={'latitude': CAMPUS_LAT})
    assert missing.status_code == 400

    out_of_range = client.post(
        f'/verify/{event_id}/check', json={'latitude': 120.0, 'longitude': 76.0}
    )
    assert out_of_range.status_code == 400


def test_photo_is_stored_and_only_visible_to_owner_and_organizer(
    app, client, user_factory
):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    response = client.post(
        f'/verify/{event_id}/check',
        json={
            'latitude': CAMPUS_LAT,
            'longitude': CAMPUS_LNG,
            'accuracy': 10,
            'image': _jpeg_data_url(),
        },
    )
    assert response.status_code == 200
    record_id = response.get_json()['record_id']

    owner_view = client.get(f'/verify/{record_id}/image')
    assert owner_view.status_code == 200
    assert owner_view.mimetype == 'image/jpeg'

    with app.app_context():
        assert GeoVerification.query.filter_by(event_id=event_id).one().image_path

    with app.app_context():
        db.session.add(user_factory('student', 'other-student@example.com', name='Other'))
        db.session.commit()

    stranger = app.test_client()
    login(stranger, 'other-student@example.com')
    blocked = stranger.get(f'/verify/{record_id}/image')
    assert blocked.status_code == 302
    assert b'/student/dashboard' in blocked.headers['Location'].encode()

    organizer_client = app.test_client()
    login(organizer_client, 'owner@example.com')
    organizer_view = organizer_client.get(f'/verify/{record_id}/image')
    assert organizer_view.status_code == 200


def test_organizer_sees_verifications_for_own_event_only(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    client.post(
        f'/verify/{event_id}/check', json={'latitude': CAMPUS_LAT, 'longitude': CAMPUS_LNG}
    )

    owner = app.test_client()
    login(owner, 'owner@example.com')
    page = owner.get(f'/organizer/events/{event_id}/verifications')
    assert page.status_code == 200
    assert b'verify-student@example.com' in page.data
    assert b'Match' in page.data

    with app.app_context():
        db.session.add(user_factory('organizer', 'rival@example.com', name='Rival'))
        db.session.commit()

    rival = app.test_client()
    login(rival, 'rival@example.com')
    blocked = rival.get(f'/organizer/events/{event_id}/verifications')
    assert blocked.status_code == 302


def test_organizer_cannot_use_the_student_verification_endpoint(app, client, user_factory):
    event_id = _setup(app, user_factory)
    organizer_client = app.test_client()
    login(organizer_client, 'owner@example.com')

    response = organizer_client.post(
        f'/verify/{event_id}/check', json={'latitude': CAMPUS_LAT, 'longitude': CAMPUS_LNG}
    )
    assert response.status_code == 302
    assert b'/organizer/dashboard' in response.headers['Location'].encode()


def test_second_verification_updates_the_same_record(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    first = client.post(
        f'/verify/{event_id}/check', json={'latitude': CAMPUS_LAT, 'longitude': CAMPUS_LNG}
    ).get_json()
    second = client.post(
        f'/verify/{event_id}/check', json={'latitude': 8.5241, 'longitude': 76.9366}
    ).get_json()

    assert first['record_id'] == second['record_id']
    with app.app_context():
        assert GeoVerification.query.filter_by(event_id=event_id).count() == 1
