from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.controllers.auth import role_required
from app.models import Event, db
from app.workflow import InvalidEventTransition, transition_event


hod_bp = Blueprint('hod', __name__)


def _dashboard_context():
    events = Event.query.order_by(Event.event_date.asc()).all()
    counts = {
        status: sum(1 for event in events if event.status == status)
        for status in ('pending_hod', 'hod_approved', 'approved', 'rejected', 'completed')
    }
    return events, counts


@hod_bp.route('/dashboard')
@role_required('hod')
def dashboard():
    events, counts = _dashboard_context()
    return render_template('hod_dashboard.html', events=events, counts=counts)


@hod_bp.route('/events/<int:event_id>/review', methods=['POST'])
@role_required('hod')
def review_event(event_id):
    event = Event.query.filter_by(id=event_id).with_for_update().first_or_404()
    if event.status != 'pending_hod':
        flash('Only programs awaiting HoD verification can be reviewed.', 'warning')
        return redirect(url_for('hod.dashboard'))

    action = request.form.get('action', '').strip().lower()
    if action == 'send_to_admin':
        target_status = 'hod_approved'
    elif action == 'reject':
        target_status = 'rejected'
    else:
        flash('Choose a valid HoD review action.', 'danger')
        return redirect(url_for('hod.dashboard'))

    try:
        transition_event(event, target_status)
    except InvalidEventTransition as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('hod.dashboard'))

    db.session.commit()
    if target_status == 'hod_approved':
        flash(f'{event.title} was verified and sent to the administrator for final approval.', 'success')
    else:
        flash(f'{event.title} was rejected by the HoD.', 'warning')
    return redirect(url_for('hod.dashboard'))
