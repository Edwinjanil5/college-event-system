from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.controllers.auth import role_required
from app.models import Event, Feedback, Registration, db
from app.workflow import utcnow


student_bp = Blueprint('student', __name__)


def can_register_for_event(event, now=None):
    current_time = now or utcnow()
    registration_count = Registration.query.filter_by(event_id=event.id).count()
    return (
        event.status == 'approved'
        and event.registration_deadline >= current_time
        and event.event_date >= current_time
        and event.max_participants > 0
        and registration_count < event.max_participants
    )


@student_bp.route('/dashboard')
@role_required('student')
def dashboard():
    now = utcnow()
    events = (
        Event.query
        .filter(Event.status == 'approved')
        .filter(Event.event_date >= now)
        .filter(Event.registration_deadline >= now)
        .order_by(Event.event_date.asc())
        .all()
    )
    registrations = Registration.query.filter_by(user_id=current_user.id).all()
    registered_event_ids = {item.event_id for item in registrations}
    completed_events = (
        Event.query
        .join(Registration, Registration.event_id == Event.id)
        .filter(Registration.user_id == current_user.id)
        .filter(Event.status == 'completed')
        .order_by(Event.event_date.desc())
        .all()
    )
    feedback_event_ids = {
        feedback.event_id
        for feedback in Feedback.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        'student_dashboard.html',
        events=events,
        registered_event_ids=registered_event_ids,
        completed_events=completed_events,
        feedback_event_ids=feedback_event_ids,
    )


@student_bp.route('/events/<int:event_id>/register', methods=['POST'])
@role_required('student')
def register_for_event(event_id):
    event = Event.query.filter_by(id=event_id).with_for_update().first_or_404()

    if not can_register_for_event(event):
        flash('This event is not open for registration.', 'danger')
        return redirect(url_for('student.dashboard'))

    existing = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if existing:
        flash('You are already registered for this event.', 'warning')
        return redirect(url_for('student.dashboard'))

    registration = Registration(user_id=current_user.id, event_id=event.id)
    db.session.add(registration)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('You are already registered for this event.', 'warning')
        return redirect(url_for('student.dashboard'))

    flash('Successfully registered for the event.', 'success')
    return redirect(url_for('student.dashboard'))


@student_bp.route('/events/<int:event_id>/payment-info')
@role_required('student')
def payment_info(event_id):
    """Show the safe, non-transactional payment policy for a paid event."""
    event = db.get_or_404(Event, event_id)
    registration = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if registration is None:
        flash('Register for the event before viewing payment instructions.', 'warning')
        return redirect(url_for('student.dashboard'))
    if event.ticket_fee <= 0:
        flash('This program is free and does not require payment.', 'info')
        return redirect(url_for('student.dashboard'))

    flash(
        f'{event.title} is a paid program. CampusPulse does not process or verify payments; '
        'contact the event organizer for the approved payment instructions and keep your receipt.',
        'info',
    )
    return redirect(url_for('student.dashboard'))


@student_bp.route('/events/<int:event_id>/cancel', methods=['POST'])
@role_required('student')
def cancel_registration(event_id):
    event = Event.query.filter_by(id=event_id).with_for_update().first_or_404()
    registration = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if registration is None:
        flash('You are not registered for this event.', 'warning')
        return redirect(url_for('student.dashboard'))

    if event.registration_deadline <= utcnow():
        flash('Registration cannot be cancelled after the deadline.', 'danger')
        return redirect(url_for('student.dashboard'))

    db.session.delete(registration)
    db.session.commit()
    flash('Registration cancelled successfully.', 'success')
    return redirect(url_for('student.dashboard'))


@student_bp.route('/events/<int:event_id>/feedback', methods=['POST'])
@role_required('student')
def submit_feedback(event_id):
    event = db.get_or_404(Event, event_id)
    registration = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if registration is None:
        flash('Only registered students can submit feedback for this event.', 'danger')
        return redirect(url_for('student.dashboard'))

    if event.status != 'completed':
        flash('Feedback can only be submitted after the event is marked complete.', 'danger')
        return redirect(url_for('student.dashboard'))

    try:
        rating = int(request.form.get('rating', 0))
    except (TypeError, ValueError):
        rating = 0
    comments = request.form.get('comments', '').strip()
    if rating < 1 or rating > 5:
        flash('Rating must be between 1 and 5.', 'danger')
        return redirect(url_for('student.dashboard'))
    if len(comments) > 2_000:
        flash('Feedback comments must be 2,000 characters or fewer.', 'danger')
        return redirect(url_for('student.dashboard'))

    existing = Feedback.query.filter_by(event_id=event.id, user_id=current_user.id).first()
    if existing:
        flash('You have already submitted feedback for this event.', 'warning')
        return redirect(url_for('student.dashboard'))

    feedback = Feedback(event_id=event.id, user_id=current_user.id, rating=rating, comments=comments)
    db.session.add(feedback)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('You have already submitted feedback for this event.', 'warning')
        return redirect(url_for('student.dashboard'))
    flash('Feedback submitted successfully.', 'success')
    return redirect(url_for('student.dashboard'))
