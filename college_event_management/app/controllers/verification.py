"""Geolocation cross-match verification (attendance evidence).

The browser captures a photo and a GPS reading, then the server compares the
captured geolocation against the constant campus geolocation using the trained
cross-match model in :mod:`app.geo_matching`. A "random shot" mode is also
provided so the comparison can be demonstrated with random geolocations
without a device GPS.
"""

from __future__ import annotations

import base64
import binascii
import os
import random
import re
import uuid

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.controllers.auth import role_required
from app.geo_matching import GeoPoint, get_model, haversine_m, random_shot
from app.models import Event, GeoVerification, Registration, db
from app.workflow import utcnow


verification_bp = Blueprint('verification', __name__)

ALLOWED_SOURCES = {'device', 'random_shot'}
IMAGE_DATA_URL = re.compile(r'^data:image/(jpeg|jpg|png);base64,([A-Za-z0-9+/=]+)$')
MAX_ACCURACY_M = 5000.0


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def campus_reference() -> GeoPoint:
    """The constant reference geolocation of the college."""
    return GeoPoint(
        latitude=float(current_app.config['CAMPUS_LATITUDE']),
        longitude=float(current_app.config['CAMPUS_LONGITUDE']),
    )


def campus_radius_m() -> float:
    return float(current_app.config.get('CAMPUS_RADIUS_M', 250.0))


def campus_settings() -> dict:
    reference = campus_reference()
    return {
        'name': current_app.config.get('CAMPUS_NAME', 'Campus'),
        'address': current_app.config.get('CAMPUS_ADDRESS', ''),
        'latitude': reference.latitude,
        'longitude': reference.longitude,
        'radius_m': campus_radius_m(),
    }


def load_model():
    return get_model(
        reference=campus_reference(),
        radius_m=campus_radius_m(),
        campus_name=current_app.config.get('CAMPUS_NAME', 'Campus'),
        folder=current_app.config.get('GEO_MODEL_FOLDER'),
    )


def attendance_folder() -> str:
    folder = os.path.abspath(current_app.config.get('ATTENDANCE_FOLDER', 'uploads/attendance'))
    os.makedirs(folder, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------
def _approved_registration(event_id: int) -> Registration | None:
    return Registration.query.filter_by(
        user_id=current_user.id,
        event_id=event_id,
        status='approved',
    ).first()


def _event_for_student(event_id: int) -> Event | None:
    event = Event.query.filter_by(id=event_id).first()
    if event is None:
        return None
    if event.status not in {'approved', 'completed'}:
        return None
    return event


def _coerce_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------
def _decode_image(data_url: str) -> bytes | None:
    match = IMAGE_DATA_URL.match(data_url.strip())
    if not match:
        return None
    payload = match.group(2)
    limit = int(current_app.config.get('MAX_VERIFICATION_IMAGE_BYTES', 400 * 1024))
    if len(payload) * 3 // 4 > limit:
        return None
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw or len(raw) > limit:
        return None
    # Reject anything that is not really an image (basic magic-byte check).
    if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG')):
        return None
    return raw


def _store_image(data_url: str, extension: str) -> str | None:
    raw = _decode_image(data_url)
    if raw is None:
        return None
    filename = f'verify_{current_user.id}_{uuid.uuid4().hex}.{extension}'
    try:
        with open(os.path.join(attendance_folder(), filename), 'wb') as handle:
            handle.write(raw)
    except OSError:
        current_app.logger.warning('Could not store verification image')
        return None
    return filename


def _remove_image(filename):
    if not filename:
        return
    try:
        path = os.path.join(attendance_folder(), filename)
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        current_app.logger.warning('Could not remove verification image')


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
@verification_bp.route('/<int:event_id>')
@role_required('student')
def verify_event(event_id):
    event = Event.query.filter_by(id=event_id).first_or_404()
    registration = _approved_registration(event_id)
    if registration is None:
        flash(
            'Location verification needs an approved registration for this event.',
            'warning',
        )
        return redirect(url_for('student.dashboard'))

    model = load_model()
    records = (
        GeoVerification.query.filter_by(user_id=current_user.id)
        .order_by(GeoVerification.captured_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        'verify_location.html',
        event=event,
        records=records,
        campus=campus_settings(),
        model_info={
            'version': model.model_version,
            'accuracy': round(model.accuracy * 100, 2),
            'decision_radius_m': round(model.decision_radius_m, 1),
            'training_samples': model.training_samples,
        },
        threshold=float(current_app.config.get('GEO_MATCH_THRESHOLD', 0.5)),
    )


@verification_bp.route('/<int:event_id>/random-shot', methods=['POST'])
@role_required('student')
def random_shot_point(event_id):
    """Return a random geolocation so the cross-match can be demonstrated."""
    event = Event.query.filter_by(id=event_id).first_or_404()
    if _approved_registration(event_id) is None:
        return jsonify({'error': 'Approved registration required.'}), 403

    reference = campus_reference()
    radius = campus_radius_m()
    point = random_shot(reference, radius, rng=random.SystemRandom())
    distance = haversine_m(reference.latitude, reference.longitude, point.latitude, point.longitude)
    return jsonify(
        {
            'event_id': event.id,
            'source': 'random_shot',
            'point': point.as_dict(),
            'simulated_inside_campus': distance <= radius,
            'campus': campus_settings(),
        }
    )


@verification_bp.route('/<int:event_id>/check', methods=['POST'])
@role_required('student')
def check_location(event_id):
    """Cross-match the submitted geolocation against the campus geolocation."""
    event = _event_for_student(event_id)
    if event is None:
        return jsonify({'error': 'Event is not open for verification.'}), 404

    registration = _approved_registration(event_id)
    if registration is None:
        return jsonify({'error': 'Approved registration required.'}), 403

    payload = request.get_json(silent=True) or {}
    latitude = _coerce_float(payload.get('latitude'))
    longitude = _coerce_float(payload.get('longitude'))
    if latitude is None or longitude is None:
        return jsonify({'error': 'A latitude and longitude are required.'}), 400
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return jsonify({'error': 'The captured geolocation is out of range.'}), 400

    accuracy = _coerce_float(payload.get('accuracy'))
    if accuracy is not None and not 0.0 <= accuracy <= MAX_ACCURACY_M:
        accuracy = None

    source = payload.get('source', 'device')
    if source not in ALLOWED_SOURCES:
        source = 'device'

    point = GeoPoint(latitude=latitude, longitude=longitude, accuracy_m=accuracy)
    model = load_model()
    threshold = float(current_app.config.get('GEO_MATCH_THRESHOLD', 0.5))
    result = model.match(point, threshold=threshold)

    image_path = None
    image = payload.get('image')
    if isinstance(image, str) and image.strip():
        extension = 'png' if 'image/png' in image[:32] else 'jpg'
        image_path = _store_image(image, extension)

    record = GeoVerification.query.filter_by(
        user_id=current_user.id, event_id=event_id
    ).first()
    previous_image = record.image_path if record else None
    if record is None:
        record = GeoVerification(user_id=current_user.id, event_id=event_id)
        db.session.add(record)

    record.source = source
    record.latitude = point.latitude
    record.longitude = point.longitude
    record.accuracy_m = point.accuracy_m
    record.distance_m = result.distance_m
    record.match_probability = result.probability
    record.verdict = result.verdict
    record.model_version = result.model_version
    record.campus_name = result.campus_name
    record.campus_latitude = result.campus_latitude
    record.campus_longitude = result.campus_longitude
    record.captured_at = utcnow()
    if image_path:
        record.image_path = image_path

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A verification already exists for this event.'}), 409

    if previous_image and previous_image != record.image_path:
        _remove_image(previous_image)

    return jsonify(
        {
            'record_id': record.id,
            'verdict': result.verdict,
            'matched': result.matched,
            'probability': round(result.probability, 4),
            'distance_m': round(result.distance_m, 1),
            'accuracy_m': record.accuracy_m,
            'source': record.source,
            'candidate': point.as_dict(),
            'campus': campus_settings(),
            'model': {
                'version': result.model_version,
                'accuracy': round(model.accuracy * 100, 2),
                'decision_radius_m': round(model.decision_radius_m, 1),
                'training_samples': model.training_samples,
            },
            'threshold': threshold,
            'captured_at': record.captured_at.isoformat(),
        }
    )


@verification_bp.route('/<int:verification_id>/image')
@role_required('student', 'organizer', 'admin')
def verification_image(verification_id):
    """Serve a captured photo only to its owner or the owning organizer."""
    record = db.session.get(GeoVerification, verification_id)
    if record is None or not record.image_path:
        return jsonify({'error': 'No image available.'}), 404

    if current_user.role == 'student' and record.user_id != current_user.id:
        flash('You cannot view another student\'s verification photo.', 'danger')
        return redirect(url_for('student.dashboard'))
    if current_user.role == 'organizer' and record.event.organizer_id != current_user.id:
        flash('You cannot view verifications for another organizer\'s event.', 'danger')
        return redirect(url_for('organizer.dashboard'))

    path = os.path.join(attendance_folder(), record.image_path)
    if not os.path.isfile(path):
        return jsonify({'error': 'The stored image is no longer available.'}), 404
    return send_file(path, mimetype='image/jpeg', max_age=0)
