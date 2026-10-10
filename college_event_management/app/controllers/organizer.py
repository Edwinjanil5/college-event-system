from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.controllers.auth import role_required
from app.models import Event, GeoVerification, Registration, db
from app.workflow import InvalidEventTransition, transition_event, utcnow


organizer_bp = Blueprint('organizer', __name__)
MAX_PARTICIPANTS = 100_000
MAX_TICKET_FEE = Decimal('1000000.00')


def _dashboard_context():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.event_date.desc()).all()
    counts = {
        status: sum(1 for event in events if event.status == status)
        for status in ('pending_hod', 'hod_approved', 'approved', 'completed')
    }
    teacher_requests = (
        Registration.query
        .join(Event, Registration.event_id == Event.id)
        .filter(Event.organizer_id == current_user.id)
        .filter(Registration.status == 'pending_teacher')
        .order_by(Registration.registered_at.asc())
        .all()
    )
    return events, counts, teacher_requests


def _parse_local_datetime(value, field_name):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} is not a valid date and time.') from exc
    if parsed.tzinfo is not None:
        raise ValueError('Use local date and time values without a timezone suffix.')
    return parsed


@organizer_bp.route('/dashboard')
@role_required('organizer')
def dashboard():
    events, counts, teacher_requests = _dashboard_context()
    return render_template(
        'organizer_dashboard.html',
        events=events,
        counts=counts,
        teacher_requests=teacher_requests,
    )


@organizer_bp.route('/profile/class-incharge', methods=['POST'])
@role_required('organizer')
def update_class_incharge_status():
    value = request.form.get('class_incharge_status', '').strip().lower()
    if value not in {'yes', 'no'}:
        flash('Choose whether you are a class incharge.', 'danger')
        return redirect(url_for('organizer.dashboard'))

    current_user.is_class_incharge = value == 'yes'
    db.session.commit()
    status = 'Class incharge' if current_user.is_class_incharge else 'Regular organizer'
    flash(f'Organizer status updated: {status}.', 'success')
    return redirect(url_for('organizer.dashboard'))


@organizer_bp.route('/registrations/<int:registration_id>/review', methods=['POST'])
@role_required('organizer')
def review_registration(registration_id):
    registration = Registration.query.filter_by(id=registration_id).with_for_update().first_or_404()
    event = registration.event
    action = request.form.get('action', '').strip().lower()
    note = request.form.get('teacher_note', '').strip()

    if registration.teacher_id != current_user.id and event.organizer_id != current_user.id:
        flash('You cannot review a registration for another class teacher.', 'danger')
        return redirect(url_for('organizer.dashboard'))
    if not current_user.is_class_incharge:
        flash(
            'Set "Class teacher" to Yes in your organizer profile before reviewing '
            'student registration requests.',
            'warning',
        )
        return redirect(url_for('organizer.dashboard'))
    if registration.status != 'pending_teacher':
        flash('This registration request has already been reviewed.', 'info')
        return redirect(url_for('organizer.dashboard'))
    if action not in {'approve', 'reject'}:
        flash('Choose a valid class teacher review action.', 'danger')
        return redirect(url_for('organizer.dashboard'))
    if len(note) > 500:
        flash('Teacher notes must be 500 characters or fewer.', 'danger')
        return redirect(url_for('organizer.dashboard'))

    registration.status = 'approved' if action == 'approve' else 'rejected'
    registration.teacher_id = current_user.id
    registration.reviewed_at = utcnow()
    registration.teacher_note = note or None
    db.session.commit()

    if action == 'approve':
        flash(f'Approved {registration.user.name} for {event.title}.', 'success')
    else:
        flash(f'Declined {registration.user.name} for {event.title}.', 'warning')
    return redirect(url_for('organizer.dashboard'))


@organizer_bp.route('/events/<int:event_id>/verifications')
@role_required('organizer')
def event_verifications(event_id):
    event = Event.query.filter_by(id=event_id).first_or_404()
    if event.organizer_id != current_user.id:
        flash('You cannot view attendance verifications for another organizer\'s event.', 'danger')
        return redirect(url_for('organizer.dashboard'))

    records = (
        GeoVerification.query
        .filter_by(event_id=event.id)
        .order_by(GeoVerification.captured_at.desc())
        .all()
    )
    matched = sum(1 for record in records if record.verdict == 'match')
    return render_template(
        'event_verifications.html',
        event=event,
        records=records,
        matched=matched,
        unmatched=len(records) - matched,
    )


@organizer_bp.route('/events/new', methods=['GET', 'POST'])
@role_required('organizer')
def create_event():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        venue = request.form.get('venue', '').strip()
        event_date_value = request.form.get('event_date', '').strip()
        deadline_value = request.form.get('registration_deadline', '').strip()
        is_intercollege = request.form.get('is_intercollege') == 'on'
        fee_type = request.form.get('fee_type', 'free')
        fee_value = request.form.get('ticket_fee', '0')

        try:
            max_participants = int(request.form.get('max_participants', ''))
        except (TypeError, ValueError):
            max_participants = 0

        error = None
        if not all((title, venue, event_date_value, deadline_value)):
            error = 'Please fill in all required event details.'
        elif len(title) > 150 or len(venue) > 150 or len(description) > 10_000:
            error = 'One or more event fields exceed the allowed length.'
        elif not 1 <= max_participants <= MAX_PARTICIPANTS:
            error = f'Maximum participants must be between 1 and {MAX_PARTICIPANTS:,}.'
        else:
            try:
                event_date = _parse_local_datetime(event_date_value, 'Event date')
                registration_deadline = _parse_local_datetime(deadline_value, 'Registration deadline')
                now = utcnow()
                if event_date <= now:
                    error = 'Event date must be in the future.'
                elif registration_deadline <= now:
                    error = 'Registration deadline must be in the future.'
                elif registration_deadline >= event_date:
                    error = 'Registration deadline must be before the event date.'

                if fee_type == 'paid':
                    ticket_fee = Decimal(str(fee_value))
                    if not ticket_fee.is_finite() or ticket_fee < 0 or ticket_fee > MAX_TICKET_FEE:
                        raise InvalidOperation
                    ticket_fee = ticket_fee.quantize(Decimal('0.01'))
                elif fee_type == 'free':
                    ticket_fee = Decimal('0.00')
                else:
                    error = error or 'Choose a valid program fee type.'
                    ticket_fee = Decimal('0.00')
            except (InvalidOperation, ValueError, TypeError) as exc:
                error = error or str(exc) or 'Please enter valid event dates and fee details.'

        if error:
            flash(error, 'danger')
            events, counts, teacher_requests = _dashboard_context()
            return render_template(
                'organizer_dashboard.html',
                events=events,
                counts=counts,
                teacher_requests=teacher_requests,
            )

        event = Event(
            title=title,
            description=description,
            venue=venue,
            event_date=event_date,
            registration_deadline=registration_deadline,
            max_participants=max_participants,
            is_intercollege=is_intercollege,
            ticket_fee=ticket_fee,
            organizer_id=current_user.id,
            status='pending_hod',
        )
        db.session.add(event)
        db.session.commit()
        fee_label = 'free' if ticket_fee == 0 else f'₹{ticket_fee:.2f}'
        flash(f'Event submitted for HoD verification with a {fee_label} ticket fee.', 'success')
        return redirect(url_for('organizer.dashboard'))

    events, counts, teacher_requests = _dashboard_context()
    return render_template(
        'organizer_dashboard.html',
        events=events,
        counts=counts,
        teacher_requests=teacher_requests,
    )


@organizer_bp.route('/events/<int:event_id>/complete', methods=['POST'])
@role_required('organizer')
def mark_event_completed(event_id):
    event = Event.query.filter_by(id=event_id).with_for_update().first_or_404()
    if event.organizer_id != current_user.id:
        flash('You cannot manage this event.', 'danger')
        return redirect(url_for('organizer.dashboard'))

    try:
        transition_event(event, 'completed')
    except InvalidEventTransition as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('organizer.dashboard'))

    db.session.commit()
    flash('Event marked as completed. Feedback is now open for registered students.', 'success')
    return redirect(url_for('organizer.dashboard'))
