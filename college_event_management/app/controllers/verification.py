"""Geolocation and image verification for CampusPulse.

This module is the single backend surface for the student's existing
photo-upload flow. It:

* cross-checks the reported geolocation against the campus area (radius or an
  optional verified polygon) and records MATCH / MISMATCH / INCONCLUSIVE /
  MISSING without ever treating browser input as proof of presence;
* compares the submitted photo with the configured campus reference images and
  records an indicative visual-similarity label;
* combines both signals into a structured, reviewable decision;
* lets authorised faculty record a human decision that stays clearly separate
  from the model's suggestion.

Security notes: the student's identity always comes from the session, never
from the request body; coordinates are validated and range-checked; uploaded
bytes are decoded rather than trusted by MIME type; and other students'
precise coordinates are never exposed.
"""

from __future__ import annotations

import base64
import binascii
import os
import random
import re
import uuid
from datetime import datetime, timedelta, timezone

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
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.campus import (
    INCONCLUSIVE as GPS_INCONCLUSIVE,
    LOCATION_MATCH,
    LOCATION_MISMATCH,
    MISSING as GPS_MISSING,
    campus_from_config,
    evaluate_location,
    mask_coordinate,
)
from app.controllers.auth import role_required
from app.decision import FACULTY_REVIEW, DecisionPolicy, decide
from app.geo_matching import GeoPoint, get_model, haversine_m, random_shot
from app.image_verification import (
    INVALID_IMAGE,
    ImageRejected,
    build_embedding_backend,
    build_reference_index,
    decode_image,
    list_reference_images,
    verify_image_against_references,
)
from app.models import Event, GeoVerification, Registration, db
from app.workflow import utcnow


verification_bp = Blueprint('verification', __name__)

ALLOWED_SOURCES = {'device', 'random_shot'}
IMAGE_DATA_URL = re.compile(r'^data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=]+)$')

REVIEW_DECISIONS = {
    'CONFIRMED_CAMPUS': 'Confirmed as on campus',
    'REJECTED': 'Rejected after review',
    'NEEDS_MORE_INFO': 'Needs more information',
}
FACULTY_ROLES = {'organizer', 'hod', 'admin'}


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
def campus_area():
    return campus_from_config(current_app.config)


def campus_settings() -> dict:
    return campus_area().as_dict()


def _reference_index():
    """Build (and memoise) the campus reference embedding index."""
    backend_name = current_app.config.get('IMAGE_EMBEDDING_BACKEND', 'perceptual')
    folder = current_app.config.get('REFERENCE_IMAGE_FOLDER', '')
    cache_path = current_app.config.get('REFERENCE_IMAGE_CACHE_FILE', '')
    max_bytes = int(current_app.config.get('MAX_REFERENCE_IMAGE_BYTES', 10 * 1024 * 1024))

    signature = (backend_name, folder, cache_path)
    store = current_app.extensions.setdefault('campuspulse_verification', {})
    if store.get('signature') != signature:
        backend = build_embedding_backend(backend_name)
        index = None
        if backend is not None:
            index = build_reference_index(folder, backend, cache_path=cache_path, max_bytes=max_bytes)
        store.update(
            signature=signature,
            backend=backend,
            index=index,
            reference_names=list_reference_images(folder),
        )
    return store['backend'], store['index'], store['reference_names']


def _decision_policy() -> DecisionPolicy:
    return DecisionPolicy(
        max_reliable_accuracy_m=float(current_app.config.get('GPS_MAX_RELIABLE_ACCURACY_M', 100)),
        similarity_threshold=float(current_app.config.get('IMAGE_SIMILARITY_THRESHOLD', 0.92)),
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
        user_id=current_user.id, event_id=event_id, status='approved'
    ).first()


def _event_for_student(event_id: int) -> Event | None:
    event = Event.query.filter_by(id=event_id).first()
    if event is None or event.status not in {'approved', 'completed'}:
        return None
    return event


def _can_review(record: GeoVerification) -> bool:
    """Faculty authorisation: the owning organizer, any HoD, or an admin."""
    if current_user.role == 'admin' or current_user.role == 'hod':
        return True
    if current_user.role == 'organizer':
        return record.event.organizer_id == current_user.id
    return False


def _coerce_float(value, default=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float('inf'), float('-inf')):
        return default
    return result


def _parse_capture_time(raw) -> datetime | None:
    """Accept a client capture timestamp, clamped to a sane window."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    now = utcnow()
    if parsed > now + timedelta(minutes=5):
        return now
    if parsed < now - timedelta(days=1):
        return now - timedelta(days=1)
    return parsed


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------
def _extract_image(payload) -> tuple[bytes | None, str | None]:
    """Pull validated image bytes out of the request payload.

    The declared MIME type is ignored; the bytes themselves are decoded and
    the true format is checked before anything is stored.
    """
    data_url = payload.get('image')
    if not isinstance(data_url, str) or not data_url.strip():
        return None, None
    match = IMAGE_DATA_URL.match(data_url.strip())
    if not match:
        return None, None
    payload_b64 = match.group(2)
    limit = int(current_app.config.get('MAX_VERIFICATION_IMAGE_BYTES', 400 * 1024))
    if len(payload_b64) * 3 // 4 > limit:
        return None, None
    try:
        raw = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError):
        return None, None
    if not raw or len(raw) > limit:
        return None, None
    try:
        decode_image(raw, limit)  # rejects non-images and unsupported formats
    except ImageRejected:
        return None, None
    extension = 'png' if raw.startswith(b'\x89PNG') else ('webp' if b'WEBP' in raw[:16] else 'jpg')
    return raw, extension


def _store_image(raw: bytes, extension: str) -> str | None:
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
# Student-facing views
# ---------------------------------------------------------------------------
@verification_bp.route('/status')
@login_required
def status():
    """Operational view of the verification components (no personal data)."""
    backend, index, names = _reference_index()
    campus = campus_area()
    return jsonify(
        {
            'campus': campus.as_dict(),
            'image_backend': backend.name if backend else None,
            'image_backend_available': backend is not None,
            'reference_images': names,
            'reference_count': len(index) if index else 0,
            'similarity_threshold': _decision_policy().similarity_threshold,
            'max_reliable_accuracy_m': _decision_policy().max_reliable_accuracy_m,
            'retention_days': current_app.config.get('VERIFICATION_RETENTION_DAYS', 180),
            'note': 'Visual similarity is indicative only and is not proof of origin.',
        }
    )


@verification_bp.route('/<int:event_id>')
@role_required('student')
def verify_event(event_id):
    event = Event.query.filter_by(id=event_id).first_or_404()
    if _approved_registration(event_id) is None:
        flash(
            'Location verification needs an approved registration for this event.',
            'warning',
        )
        return redirect(url_for('student.dashboard'))

    backend, index, names = _reference_index()
    records = (
        GeoVerification.query.filter_by(user_id=current_user.id)
        .order_by(GeoVerification.captured_at.desc())
        .limit(10)
        .all()
    )
    policy = _decision_policy()
    return render_template(
        'verify_location.html',
        event=event,
        records=records,
        campus=campus_settings(),
        image_enabled=backend is not None and bool(index),
        reference_names=names,
        similarity_threshold=policy.similarity_threshold,
        max_reliable_accuracy_m=policy.max_reliable_accuracy_m,
        retention_days=current_app.config.get('VERIFICATION_RETENTION_DAYS', 180),
    )


@verification_bp.route('/<int:event_id>/random-shot', methods=['POST'])
@role_required('student')
def random_shot_point(event_id):
    """Return a random geolocation so the cross-match can be demonstrated."""
    event = Event.query.filter_by(id=event_id).first_or_404()
    if _approved_registration(event_id) is None:
        return jsonify({'error': 'Approved registration required.'}), 403

    campus = campus_area()
    point = random_shot(campus.reference, campus.radius_m, rng=random.SystemRandom())
    distance = haversine_m(campus.latitude, campus.longitude, point.latitude, point.longitude)
    return jsonify(
        {
            'event_id': event.id,
            'source': 'random_shot',
            'point': point.as_dict(),
            'simulated_inside_campus': campus.contains(point),
            'campus': campus.as_dict(),
            'approx_distance_m': round(distance, 1),
        }
    )


@verification_bp.route('/<int:event_id>/check', methods=['POST'])
@role_required('student')
def check_location(event_id):
    """Verify a submitted location and photo and store the combined outcome."""
    event = _event_for_student(event_id)
    if event is None:
        return jsonify({'error': 'Event is not open for verification.'}), 404

    # Identity comes from the session; an event id in the body is never trusted.
    if _approved_registration(event_id) is None:
        return jsonify({'error': 'Approved registration required.'}), 403

    payload = request.get_json(silent=True) or {}
    captured_at = _parse_capture_time(payload.get('captured_at'))
    source = payload.get('source', 'device')
    if source not in ALLOWED_SOURCES:
        source = 'device'

    campus = campus_area()
    policy = _decision_policy()

    gps = evaluate_location(
        campus,
        payload.get('latitude'),
        payload.get('longitude'),
        payload.get('accuracy'),
        max_reliable_accuracy_m=policy.max_reliable_accuracy_m,
        captured_at=captured_at.isoformat() if captured_at else None,
    )

    raw_image, extension = _extract_image(payload)
    backend, index, _names = _reference_index()
    backend_name = backend.name if backend else current_app.config.get(
        'IMAGE_EMBEDDING_BACKEND', 'perceptual'
    )
    image_result = verify_image_against_references(
        raw_image,
        index,
        backend_name,
        int(current_app.config.get('MAX_VERIFICATION_IMAGE_BYTES', 400 * 1024)),
        policy.similarity_threshold,
    )
    if image_result.status == INVALID_IMAGE:
        raw_image, extension = None, None

    outcome = decide(gps, image_result, policy)

    # Legacy soft probability retained for continuity with earlier releases.
    probability = None
    latitude = _coerce_float(payload.get('latitude'))
    longitude = _coerce_float(payload.get('longitude'))
    if (
        latitude is not None
        and longitude is not None
        and gps.status in {LOCATION_MATCH, LOCATION_MISMATCH}
    ):
        try:
            model = get_model(
                reference=campus.reference,
                radius_m=campus.radius_m,
                campus_name=campus.name,
                folder=current_app.config.get('GEO_MODEL_FOLDER'),
            )
            probability = round(
                model.probability(GeoPoint(latitude, longitude, gps.accuracy_m)), 4
            )
        except (TypeError, ValueError):
            probability = None

    record = GeoVerification.query.filter_by(
        user_id=current_user.id, event_id=event_id
    ).first()
    previous_image = record.image_path if record else None
    if record is None:
        record = GeoVerification(user_id=current_user.id, event_id=event_id)
        db.session.add(record)

    image_filename = _store_image(raw_image, extension) if raw_image else None

    record.source = source
    record.latitude = float(payload['latitude']) if _valid_number(payload.get('latitude')) else None
    record.longitude = (
        float(payload['longitude']) if _valid_number(payload.get('longitude')) else None
    )
    record.accuracy_m = gps.accuracy_m
    record.distance_m = gps.distance_m
    record.match_probability = probability
    record.verdict = 'match' if gps.status == LOCATION_MATCH else 'mismatch'
    record.model_version = current_app.config.get('GEO_MATCH_MODEL_VERSION', 'geo-crossmatch-1.0.0')
    record.campus_name = campus.name
    record.campus_latitude = campus.latitude
    record.campus_longitude = campus.longitude

    record.gps_status = gps.status
    record.gps_reason = (gps.reason or None)
    record.gps_boundary_source = gps.boundary_source
    record.location_captured_at = captured_at or utcnow()
    record.verified_at = utcnow()
    record.captured_at = captured_at or utcnow()

    record.image_status = image_result.status
    record.image_similarity = image_result.similarity
    record.image_best_reference = image_result.best_reference
    record.image_backend = image_result.backend or None
    record.image_model_version = (index.version if index else None)
    record.image_reference_count = image_result.reference_count

    record.final_decision = outcome.final_decision
    record.decision_flags = (outcome.flag_text or None)
    record.decision_rationale = outcome.rationale or None
    # A new submission invalidates a previous human decision.
    record.review_decision = None
    record.review_note = None
    record.reviewed_at = None
    record.reviewed_by_id = None

    if image_filename:
        record.image_path = image_filename

    try:
        db.session.commit()
    except IntegrityError:
        # Upserting on (user, event) means a genuine duplicate should not
        # occur, so log the real cause instead of reporting a misleading one.
        db.session.rollback()
        current_app.logger.exception('Could not store verification record')
        return jsonify({'error': 'The verification could not be stored. Please try again.'}), 409

    if previous_image and previous_image != record.image_path:
        _remove_image(previous_image)

    current_app.logger.info(
        'verification recorded user_id=%s event_id=%s gps=%s image=%s decision=%s',
        current_user.id,
        event_id,
        gps.status,
        image_result.status,
        outcome.final_decision,
    )

    body = outcome.as_dict()
    body.update(
        {
            'record_id': record.id,
            'source': record.source,
            'campus': campus.as_dict(),
            'review_pending': True,
            'message': (
                'Your submission was recorded and sent for faculty review. '
                'Location and photo checks are advisory, not proof of presence.'
            ),
        }
    )
    return jsonify(body)


def _valid_number(value) -> bool:
    number = _coerce_float(value)
    return number is not None


@verification_bp.route('/<int:verification_id>/image')
@role_required('student', 'organizer', 'hod', 'admin')
def verification_image(verification_id):
    """Serve a captured photo only to its owner or authorised reviewers."""
    record = db.session.get(GeoVerification, verification_id)
    if record is None or not record.image_path:
        return jsonify({'error': 'No image available.'}), 404

    if current_user.role == 'student' and record.user_id != current_user.id:
        flash("You cannot view another student's verification photo.", 'danger')
        return redirect(url_for('student.dashboard'))
    if current_user.role in {'organizer', 'hod'} and not _can_review(record):
        flash("You cannot view verifications for another organizer's event.", 'danger')
        return redirect(url_for('verification.review_queue'))

    path = os.path.join(attendance_folder(), record.image_path)
    if not os.path.isfile(path):
        return jsonify({'error': 'The stored image is no longer available.'}), 404
    return send_file(path, mimetype='image/jpeg', max_age=0)


# ---------------------------------------------------------------------------
# Faculty review
# ---------------------------------------------------------------------------
def _record_context(records):
    """Decorate records for display, masking coordinates for non-owners."""
    rows = []
    for record in records:
        owner = record.user_id == current_user.id
        rows.append(
            {
                'record': record,
                'show_exact_coordinates': owner or current_user.role in {'admin', 'hod'},
                'latitude': (
                    record.latitude if owner or current_user.role in {'admin', 'hod'}
                    else mask_coordinate(record.latitude)
                ),
                'longitude': (
                    record.longitude if owner or current_user.role in {'admin', 'hod'}
                    else mask_coordinate(record.longitude)
                ),
            }
        )
    return rows


@verification_bp.route('/review-queue')
@role_required('organizer', 'hod', 'admin')
def review_queue():
    """Queue of verifications awaiting a human decision."""
    query = GeoVerification.query
    if current_user.role == 'organizer':
        query = query.join(Event, GeoVerification.event_id == Event.id).filter(
            Event.organizer_id == current_user.id
        )
    records = query.order_by(
        GeoVerification.review_decision.is_(None).desc(),
        GeoVerification.captured_at.desc(),
    ).limit(100).all()
    return render_template(
        'verification_review_queue.html',
        rows=_record_context(records),
        review_decisions=REVIEW_DECISIONS,
    )


@verification_bp.route('/<int:verification_id>/review', methods=['POST'])
@role_required('organizer', 'hod', 'admin')
def review_verification(verification_id):
    """Record a human decision. Never triggered automatically by the model."""
    record = db.session.get(GeoVerification, verification_id)
    if record is None:
        flash('That verification record no longer exists.', 'warning')
        return redirect(url_for('verification.review_queue'))
    if not _can_review(record):
        flash('You cannot review this verification.', 'danger')
        return redirect(url_for('verification.review_queue'))

    decision = (request.form.get('review_decision') or '').strip().upper()
    note = (request.form.get('review_note') or '').strip()
    if decision not in REVIEW_DECISIONS:
        flash('Choose a valid review decision.', 'danger')
        return redirect(url_for('verification.review_queue'))
    if len(note) > 500:
        flash('Review notes must be 500 characters or fewer.', 'danger')
        return redirect(url_for('verification.review_queue'))

    record.review_decision = decision
    record.review_note = note or None
    record.reviewed_at = utcnow()
    record.reviewed_by_id = current_user.id
    db.session.commit()

    current_app.logger.info(
        'verification reviewed verification_id=%s reviewer=%s decision=%s',
        record.id,
        current_user.id,
        decision,
    )
    flash(f'Review recorded: {REVIEW_DECISIONS[decision]}.', 'success')
    # Always return to the review queue. Redirecting back to the referring URL
    # is fragile: it may point at a POST-only endpoint.
    return redirect(url_for('verification.review_queue'))