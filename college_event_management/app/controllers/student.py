from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.controllers.auth import role_required
from app.models import Event, Feedback, Registration, db
from app.workflow import utcnow


student_bp = Blueprint('student', __name__)


def class_teacher_for_event(event):
    """Return the class teacher who must approve registrations for this event.

    The organizer dashboard lets an organizer declare themselves the class
    teacher ("Class incharge"). Only those organizers sit in the approval loop
    for their own events, so regular organizers confirm students immediately.
    """
    organizer = event.organizer
    if organizer is not None and organizer.is_class_incharge:
        return organizer
    return None


def can_register_for_event(event, now=None):
    current_time = now or utcnow()
    registration_count = Registration.query.filter(
        Registration.event_id == event.id,
        Registration.status.in_(('pending_teacher', 'approved')),
    ).count()
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
    registration_by_event = {item.event_id: item for item in registrations}
    approved_event_ids = {
        item.event_id for item in registrations if item.status == 'approved'
    }
    pending_teacher_event_ids = {
        item.event_id for item in registrations if item.status == 'pending_teacher'
    }
    rejected_event_ids = {
        item.event_id for item in registrations if item.status == 'rejected'
    }
    completed_events = (
        Event.query
        .join(Registration, Registration.event_id == Event.id)
        .filter(Registration.user_id == current_user.id)
        .filter(Registration.status == 'approved')
        .filter(Event.status == 'completed')
        .order_by(Event.event_date.desc())
        .all()
    )
    feedback_event_ids = {
        feedback.event_id
        for feedback in Feedback.query.filter_by(user_id=current_user.id).all()
    }
    teacher_approval_event_ids = {
        event.id for event in events if class_teacher_for_event(event) is not None
    }
    return render_template(
        'student_dashboard.html',
        events=events,
        registered_event_ids=approved_event_ids,
        approved_event_ids=approved_event_ids,
        pending_teacher_event_ids=pending_teacher_event_ids,
        rejected_event_ids=rejected_event_ids,
        registration_by_event=registration_by_event,
        teacher_approval_event_ids=teacher_approval_event_ids,
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

    teacher = class_teacher_for_event(event)

    existing = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if existing and existing.status == 'approved':
        flash('Your registration for this event is already confirmed.', 'info')
        return redirect(url_for('student.dashboard'))
    if existing and existing.status == 'pending_teacher':
        flash('Your registration request is already waiting for class teacher approval.', 'info')
        return redirect(url_for('student.dashboard'))

    if existing and existing.status == 'rejected':
        existing.status = 'pending_teacher'
        existing.teacher_id = teacher.id if teacher else None
        existing.registered_at = utcnow()
        existing.reviewed_at = None
        existing.teacher_note = None
        db.session.commit()
        flash(
            f'Registration request resent to {teacher.name} for approval.'
            if teacher
            else 'Registration request submitted.',
            'success',
        )
        return redirect(url_for('student.dashboard'))

    registration = Registration(
        user_id=current_user.id,
        event_id=event.id,
        status='pending_teacher' if teacher else 'approved',
        teacher_id=teacher.id if teacher else None,
    )
    db.session.add(registration)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('You already have a registration request for this event.', 'warning')
        return redirect(url_for('student.dashboard'))

    if teacher:
        flash(
            f'Registration request sent to {teacher.name} for class teacher approval. '
            'You will be confirmed once the class teacher approves it.',
            'success',
        )
    else:
        flash('Successfully registered for the event.', 'success')
    return redirect(url_for('student.dashboard'))


@student_bp.route('/events/<int:event_id>/payment-info')
@role_required('student')
def payment_info(event_id):
    """Show the safe, non-transactional payment policy for a paid event."""
    event = db.get_or_404(Event, event_id)
    registration = Registration.query.filter_by(user_id=current_user.id, event_id=event.id).first()
    if registration is None or registration.status != 'approved':
        flash('Your registration must be approved by the class teacher before viewing payment instructions.', 'warning')
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
    if registration is None or registration.status != 'approved':
        flash('Only students with teacher-approved registration can submit feedback for this event.', 'danger')
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
