import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_bcrypt import generate_password_hash
from sqlalchemy.exc import IntegrityError

from app.controllers.auth import role_required
from app.models import Event, Feedback, PA_Points, Registration, User, db
from app.workflow import InvalidEventTransition, transition_event


admin_bp = Blueprint('admin', __name__)
EMAIL_PATTERN = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')


def calculate_pa_points(event, commit=True):
    participant_count = Registration.query.filter_by(event_id=event.id).count()
    feedback_rows = Feedback.query.filter_by(event_id=event.id).all()
    avg_rating = sum(item.rating for item in feedback_rows) / len(feedback_rows) if feedback_rows else 0.0

    base = 10
    bonus_participants = 2 if participant_count > 50 else 0
    bonus_feedback = 3 if avg_rating >= 4.0 else 0
    bonus_intercollege = 5 if event.is_intercollege else 0
    total = base + bonus_participants + bonus_feedback + bonus_intercollege

    pa_points = PA_Points.query.filter_by(event_id=event.id).first()
    if pa_points is None:
        pa_points = PA_Points(event_id=event.id, total_points=total)
        db.session.add(pa_points)
    pa_points.base_points = base
    pa_points.bonus_participants = bonus_participants
    pa_points.bonus_feedback = bonus_feedback
    pa_points.bonus_intercollege = bonus_intercollege
    pa_points.total_points = total
    if commit:
        db.session.commit()

    return {
        'event_id': event.id,
        'base': base,
        'bonus_participants': bonus_participants,
        'bonus_feedback': bonus_feedback,
        'bonus_intercollege': bonus_intercollege,
        'total': total,
        'participant_count': participant_count,
        'average_rating': round(avg_rating, 2),
    }


@admin_bp.route('/dashboard')
@role_required('admin')
def dashboard():
    events = Event.query.order_by(Event.id.desc()).all()
    return render_template('admin_dashboard.html', events=events)


@admin_bp.route('/hod/create', methods=['GET', 'POST'])
@role_required('admin')
def create_hod_account():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirmation = request.form.get('password_confirmation', '')

        error = None
        if not name or not email or not password:
            error = 'Complete all HoD account fields.'
        elif len(name) > 120 or not EMAIL_PATTERN.fullmatch(email):
            error = 'Enter a valid HoD name and email address.'
        elif len(password) < 12:
            error = 'HoD passwords must be at least 12 characters long.'
        elif password != confirmation:
            error = 'Password confirmation does not match.'
        elif User.query.filter_by(email=email).first() is not None:
            error = 'An account with that email already exists.'

        if error:
            flash(error, 'danger')
            return render_template('create_hod.html', name=name, email=email)

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password).decode('utf-8'),
            role='hod',
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('An account with that email already exists.', 'danger')
            return render_template('create_hod.html', name=name, email=email)

        flash(f'HoD account created for {email}.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('create_hod.html', name='', email='')


@admin_bp.route('/events/<int:event_id>/review', methods=['POST'])
@role_required('admin')
def review_event(event_id):
    event = Event.query.filter_by(id=event_id).with_for_update().first_or_404()
    action = request.form.get('action', '').strip().lower()

    if event.status != 'hod_approved':
        flash('Only programs forwarded by the HoD can receive final admin approval.', 'warning')
        return redirect(url_for('admin.dashboard'))

    if action not in {'approve', 'reject'}:
        flash('Choose a valid review action.', 'danger')
        return redirect(url_for('admin.dashboard'))

    target_status = 'approved' if action == 'approve' else 'rejected'
    try:
        transition_event(event, target_status)
    except InvalidEventTransition as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('admin.dashboard'))

    db.session.commit()
    flash('Event approved.' if target_status == 'approved' else 'Event rejected.', 'success' if target_status == 'approved' else 'warning')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/events/<int:event_id>/calculate_pa', methods=['POST'])
@role_required('admin')
def calculate_pa(event_id):
    event = db.get_or_404(Event, event_id)
    if event.status != 'completed':
        flash('PA points can only be calculated after an event is completed.', 'danger')
        return redirect(url_for('admin.dashboard'))

    result = calculate_pa_points(event)
    flash(f'PA points calculated for {event.title}: {result["total"]} pts.', 'success')
    return redirect(url_for('admin.dashboard'))
