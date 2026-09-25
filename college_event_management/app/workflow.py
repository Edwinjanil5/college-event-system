"""Shared event workflow rules.

Keeping transitions in one module prevents individual controllers from
accepting states that the rest of the application does not expect.
"""

from datetime import datetime, timezone


class InvalidEventTransition(ValueError):
    """Raised when a requested event status transition is not allowed."""


EVENT_TRANSITIONS = {
    'pending_hod': frozenset({'hod_approved', 'rejected'}),
    'hod_approved': frozenset({'approved', 'rejected'}),
    'approved': frozenset({'completed'}),
    'rejected': frozenset(),
    'completed': frozenset(),
}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_academic_year(now=None):
    current = now or utcnow()
    start_year = current.year if current.month >= 6 else current.year - 1
    return f'{start_year}-{start_year + 1}'


def transition_event(event, target_status, now=None):
    """Apply a valid state transition to an event and return it."""
    target_status = str(target_status or '').strip().lower()
    current_status = str(event.status or '').strip().lower()
    allowed = EVENT_TRANSITIONS.get(current_status, frozenset())

    if target_status not in allowed:
        raise InvalidEventTransition(
            f'Events cannot move from {current_status or "an unknown state"} to {target_status or "an empty state"}.'
        )

    if target_status == 'completed':
        current_time = now or utcnow()
        if event.event_date > current_time:
            raise InvalidEventTransition('An event can only be completed after its event date.')

    event.status = target_status
    return event
