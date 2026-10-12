"""Integration tests for the verification backend.

These cover the authenticated upload path, authorisation, persistence,
duplicates, privacy and the faculty review workflow.
"""

import base64
import io
from datetime import timedelta

import pytest
from PIL import Image, ImageDraw

from app.models import Event, GeoVerification, Registration, User, db
from app.workflow import utcnow


CAMPUS_LAT = 9.1557
CAMPUS_LNG = 76.7369


def login(client, email, password='password123'):
    return client.post('/login', data={'email': email, 'password': password})


def campus_photo_bytes():
    """A held-out capture of the same scene as the reference images.

    Same geometry as reference image 0, re-encoded as a second photograph.
    """
    image = Image.new('RGB', (200, 150), (205, 200, 190))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 200, 52], fill=(125, 160, 210))
    draw.rectangle([35, 60, 165, 140], fill=(235, 233, 227))
    draw.rectangle([95, 100, 118, 140], fill=(55, 55, 65))
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=70)
    return buffer.getvalue()


def unrelated_photo_bytes():
    image = Image.new('RGB', (200, 150), (20, 20, 30))
    draw = ImageDraw.Draw(image)
    for step in range(0, 200, 10):
        draw.line([(step, 150), (step + 150, 0)], fill=(250, 220, 40), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=90)
    return buffer.getvalue()


def data_url(raw):
    return 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')


def write_reference_images(app, count=2):
    """Populate the configured reference folder and reset the cached index."""
    folder = app.config['REFERENCE_IMAGE_FOLDER']
    import os

    os.makedirs(folder, exist_ok=True)
    for index in range(count):
        image = Image.new('RGB', (200, 150), (205, 200, 190))
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, 200, 52], fill=(125, 160, 210))
        draw.rectangle([35 + index * 5, 60, 165 + index * 5, 140], fill=(235, 233, 227))
        draw.rectangle([95 + index * 5, 100, 118 + index * 5, 140], fill=(55, 55, 65))
        path = os.path.join(folder, f'ref-{index + 1}.jpg')
        image.save(path, format='JPEG', quality=90)
    app.extensions.pop('campuspulse_verification', None)


def _setup(app, user_factory, *, approved=True, status='approved'):
    with app.app_context():
        student = user_factory('student', 'verify-student@example.com')
        organizer = user_factory('organizer', 'owner@example.com')
        db.session.add_all([student, organizer])
        db.session.commit()
        event = Event(
            title='Verified event',
            venue='Hall',
            event_date=utcnow() + timedelta(days=1),
            registration_deadline=utcnow() + timedelta(days=2),
            max_participants=20,
            organizer_id=organizer.id,
            status=status,
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


def _submit(client, event_id, **overrides):
    payload = {
        'latitude': CAMPUS_LAT,
        'longitude': CAMPUS_LNG,
        'accuracy': 10,
        'source': 'device',
    }
    payload.update(overrides)
    return client.post(f'/verify/{event_id}/check', json=payload)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_anonymous_submission_is_rejected(app, client, user_factory):
    event_id = _setup(app, user_factory)
    response = _submit(client, event_id)
    assert response.status_code in (302, 401, 403)
    with app.app_context():
        assert GeoVerification.query.count() == 0


def test_submission_requires_approved_registration(app, client, user_factory):
    event_id = _setup(app, user_factory, approved=False)
    login(client, 'verify-student@example.com')
    response = _submit(client, event_id)
    assert response.status_code == 403
    with app.app_context():
        assert GeoVerification.query.count() == 0


def test_submission_for_an_unknown_event_is_rejected(app, client, user_factory):
    _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    response = _submit(client, 99999)
    assert response.status_code == 404


def test_event_not_open_for_verification_is_rejected(app, client, user_factory):
    event_id = _setup(app, user_factory, status='pending_hod')
    login(client, 'verify-student@example.com')
    response = _submit(client, event_id)
    assert response.status_code == 404


def test_organizer_cannot_use_the_student_endpoint(app, client, user_factory):
    event_id = _setup(app, user_factory)
    organizer_client = app.test_client()
    login(organizer_client, 'owner@example.com')
    response = _submit(organizer_client, event_id)
    assert response.status_code == 302
    assert b'/organizer/dashboard' in response.headers['Location'].encode()


def test_identity_is_taken_from_the_session_not_the_payload(app, client, user_factory):
    """A student id in the body must not let a user write another student's record."""
    event_id = _setup(app, user_factory)
    with app.app_context():
        other = user_factory('student', 'victim@example.com')
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    login(client, 'verify-student@example.com')
    response = _submit(client, event_id, user_id=other_id, student_id=other_id)
    assert response.status_code == 200
    with app.app_context():
        records = GeoVerification.query.all()
        assert len(records) == 1
        assert records[0].user_id != other_id


# ---------------------------------------------------------------------------
# GPS outcomes through the API
# ---------------------------------------------------------------------------
def test_on_campus_submission_is_recorded_and_persisted(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')

    response = _submit(client, event_id)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['gps_verification']['status'] == 'LOCATION_MATCH'
    assert payload['gps_verification']['distance_meters'] < 5
    assert payload['review_pending'] is True

    with app.app_context():
        record = GeoVerification.query.filter_by(event_id=event_id).one()
        assert record.gps_status == 'LOCATION_MATCH'
        assert record.latitude == pytest.approx(CAMPUS_LAT)
        assert record.verified_at is not None
        assert record.location_captured_at is not None
        assert record.review_decision is None, 'a model suggestion is not a human decision'


def test_distant_submission_records_a_mismatch(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    payload = _submit(client, event_id, latitude=9.2, longitude=76.8, accuracy=10).get_json()
    assert payload['gps_verification']['status'] == 'LOCATION_MISMATCH'
    assert payload['gps_verification']['distance_meters'] > 1000


def test_poor_accuracy_records_inconclusive(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    payload = _submit(client, event_id, accuracy=900).get_json()
    assert payload['gps_verification']['status'] == 'INCONCLUSIVE'
    assert payload['final_decision'] == 'FACULTY_REVIEW'
    with app.app_context():
        assert GeoVerification.query.one().gps_status == 'INCONCLUSIVE'


def test_missing_location_is_recorded_as_missing(app, client, user_factory):
    """A denied permission must not become proof of misconduct."""
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    response = client.post(
        f'/verify/{event_id}/check',
        json={'source': 'device', 'accuracy': None},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['gps_verification']['status'] == 'MISSING'
    assert payload['final_decision'] == 'FACULTY_REVIEW'
    with app.app_context():
        record = GeoVerification.query.one()
        assert record.latitude is None
        assert record.gps_status == 'MISSING'


def test_invalid_coordinates_are_rejected_with_a_reason(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    payload = _submit(client, event_id, latitude='not-a-number').get_json()
    assert payload['gps_verification']['status'] == 'MISSING'
    assert payload['gps_verification']['reason']


def test_capture_time_from_the_client_is_clamped(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    _submit(client, event_id, captured_at='2999-01-01T00:00:00Z')
    with app.app_context():
        record = GeoVerification.query.one()
        assert record.location_captured_at <= utcnow() + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# Image evidence
# ---------------------------------------------------------------------------
def test_submission_without_reference_images_is_handled(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    payload = _submit(client, event_id, image=data_url(campus_photo_bytes())).get_json()
    assert payload['image_verification']['status'] == 'REFERENCE_IMAGES_UNAVAILABLE'
    # The photo is still stored as evidence.
    with app.app_context():
        assert GeoVerification.query.one().image_path


def test_campus_photo_produces_a_visual_match(app, client, user_factory):
    event_id = _setup(app, user_factory)
    write_reference_images(app, count=2)
    login(client, 'verify-student@example.com')
    payload = _submit(
        client, event_id, image=data_url(campus_photo_bytes())
    ).get_json()
    image_result = payload['image_verification']
    assert image_result['status'] == 'POSSIBLE_VISUAL_MATCH'
    assert image_result['similarity'] > 0.9
    assert image_result['best_reference']
    assert payload['final_decision'] == 'SUGGESTED_CAMPUS_MATCH'
    assert payload['requires_human_review'] is True


def test_unrelated_photo_does_not_auto_reject(app, client, user_factory):
    event_id = _setup(app, user_factory)
    write_reference_images(app, count=2)
    login(client, 'verify-student@example.com')
    payload = _submit(
        client, event_id, image=data_url(unrelated_photo_bytes())
    ).get_json()
    assert payload['image_verification']['status'] == 'LOW_VISUAL_SIMILARITY'
    assert payload['final_decision'] == 'FACULTY_REVIEW'
    assert 'gps_match_but_image_low_similarity' in payload['flags']


def test_disguised_non_image_upload_is_rejected(app, client, user_factory):
    event_id = _setup(app, user_factory)
    write_reference_images(app, count=1)
    login(client, 'verify-student@example.com')
    payload = _submit(
        client, event_id, image='data:image/jpeg;base64,' + base64.b64encode(b'<html>x</html>').decode()
    ).get_json()
    assert payload['image_verification']['status'] == 'INCONCLUSIVE'
    with app.app_context():
        assert GeoVerification.query.one().image_path is None


def test_oversized_upload_is_dropped(app, client, user_factory):
    event_id = _setup(app, user_factory)
    write_reference_images(app, count=1)
    login(client, 'verify-student@example.com')
    huge = b'\xff\xd8\xff' + b'\x00' * (500 * 1024)
    payload = _submit(
        client, event_id, image='data:image/jpeg;base64,' + base64.b64encode(huge).decode()
    ).get_json()
    assert payload['image_verification']['status'] == 'INCONCLUSIVE'
    with app.app_context():
        assert GeoVerification.query.one().image_path is None


def test_status_endpoint_reports_configuration(app, client, user_factory):
    _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    response = client.get('/verify/status')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['campus']['latitude'] == pytest.approx(CAMPUS_LAT)
    assert payload['image_backend'] == 'perceptual'
    assert payload['retention_days'] == 180


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------
def test_second_submission_updates_the_same_record(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    first = _submit(client, event_id).get_json()
    second = _submit(client, event_id, latitude=9.2, longitude=76.8).get_json()
    assert first['record_id'] == second['record_id']
    with app.app_context():
        assert GeoVerification.query.count() == 1


def test_resubmitting_clears_a_previous_review_decision(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']

    reviewer = app.test_client()
    login(reviewer, 'owner@example.com')
    reviewer.post(
        f'/verify/{record_id}/review',
        data={'review_decision': 'NEEDS_MORE_INFO', 'review_note': 'unclear'},
    )
    _submit(client, event_id, latitude=9.2, longitude=76.8)
    with app.app_context():
        record = db.session.get(GeoVerification, record_id)
        assert record.review_decision is None, 'new evidence invalidates the old decision'


# ---------------------------------------------------------------------------
# Faculty review
# ---------------------------------------------------------------------------
def test_review_queue_is_restricted_to_faculty(app, client, user_factory):
    _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    response = client.get('/verify/review-queue')
    assert response.status_code == 302


def test_organizer_records_a_review_decision(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']

    organizer = app.test_client()
    login(organizer, 'owner@example.com')
    queue = organizer.get('/verify/review-queue')
    assert queue.status_code == 200
    assert b'verify-student@example.com' in queue.data

    response = organizer.post(
        f'/verify/{record_id}/review',
        data={'review_decision': 'CONFIRMED_CAMPUS', 'review_note': 'Photo matches the block.'},
    )
    assert response.status_code == 302
    with app.app_context():
        record = db.session.get(GeoVerification, record_id)
        assert record.review_decision == 'CONFIRMED_CAMPUS'
        assert record.reviewed_by_id is not None
        assert record.reviewed_at is not None
        assert record.review_note == 'Photo matches the block.'


def test_organizer_cannot_review_another_organizers_event(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']

    with app.app_context():
        db.session.add(user_factory('organizer', 'rival@example.com'))
        db.session.commit()

    rival = app.test_client()
    login(rival, 'rival@example.com')
    response = rival.post(f'/verify/{record_id}/review', data={'review_decision': 'REJECTED'})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(GeoVerification, record_id).review_decision is None


def test_hod_and_admin_may_review_any_event(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']

    with app.app_context():
        db.session.add(user_factory('hod', 'hod@example.com'))
        db.session.add(user_factory('admin', 'admin@example.com'))
        db.session.commit()

    for role in ('hod', 'admin'):
        reviewer = app.test_client()
        login(reviewer, f'{role}@example.com')
        response = reviewer.post(
            f'/verify/{record_id}/review', data={'review_decision': 'NEEDS_MORE_INFO'}
        )
        assert response.status_code == 302


def test_invalid_review_decision_is_rejected(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']

    organizer = app.test_client()
    login(organizer, 'owner@example.com')
    organizer.post(f'/verify/{record_id}/review', data={'review_decision': 'AUTO_REJECT'})
    with app.app_context():
        assert db.session.get(GeoVerification, record_id).review_decision is None


def test_student_cannot_review_own_submission(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id).get_json()['record_id']
    response = client.post(f'/verify/{record_id}/review', data={'review_decision': 'CONFIRMED_CAMPUS'})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(GeoVerification, record_id).review_decision is None


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------
def test_photo_is_private_to_owner_and_reviewers(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    record_id = _submit(client, event_id, image=data_url(campus_photo_bytes())).get_json()['record_id']

    assert client.get(f'/verify/{record_id}/image').status_code == 200

    with app.app_context():
        db.session.add(user_factory('student', 'nosy@example.com'))
        db.session.commit()
    stranger = app.test_client()
    login(stranger, 'nosy@example.com')
    blocked = stranger.get(f'/verify/{record_id}/image')
    assert blocked.status_code == 302
    assert b'/student/dashboard' in blocked.headers['Location'].encode()

    organizer = app.test_client()
    login(organizer, 'owner@example.com')
    assert organizer.get(f'/verify/{record_id}/image').status_code == 200


def test_other_students_coordinates_are_masked_for_organizers(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    _submit(client, event_id)

    organizer = app.test_client()
    login(organizer, 'owner@example.com')
    page = organizer.get('/verify/review-queue')
    assert b'masked' in page.data
    # The exact submitted coordinate is not printed for the organizer.
    assert f'{CAMPUS_LAT:.5f}'.encode() not in page.data


def test_review_response_does_not_leak_internals(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    body = _submit(client, event_id, image=data_url(campus_photo_bytes())).get_json()
    serialised = str(body).lower()
    assert 'traceback' not in serialised
    assert 'app/' not in serialised
    assert 'sqlite' not in serialised


# ---------------------------------------------------------------------------
# Organizer event view
# ---------------------------------------------------------------------------
def test_organizer_sees_event_verification_summary(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    _submit(client, event_id)

    organizer = app.test_client()
    login(organizer, 'owner@example.com')
    page = organizer.get(f'/organizer/events/{event_id}/verifications')
    assert page.status_code == 200
    assert b'verify-student@example.com' in page.data
    assert b'Faculty review' in page.data


def test_organizer_cannot_view_another_organizers_verifications(app, client, user_factory):
    event_id = _setup(app, user_factory)
    with app.app_context():
        db.session.add(user_factory('organizer', 'rival@example.com'))
        db.session.commit()
    rival = app.test_client()
    login(rival, 'rival@example.com')
    assert rival.get(f'/organizer/events/{event_id}/verifications').status_code == 302


def test_random_shot_endpoint_requires_an_approved_registration(app, client, user_factory):
    event_id = _setup(app, user_factory, approved=False)
    login(client, 'verify-student@example.com')
    assert client.post(f'/verify/{event_id}/random-shot', json={}).status_code == 403


def test_random_shot_returns_valid_coordinates(app, client, user_factory):
    event_id = _setup(app, user_factory)
    login(client, 'verify-student@example.com')
    response = client.post(f'/verify/{event_id}/random-shot', json={})
    assert response.status_code == 200
    point = response.get_json()['point']
    assert -90.0 <= point['latitude'] <= 90.0
    assert -180.0 <= point['longitude'] <= 180.0