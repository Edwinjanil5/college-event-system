from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import CheckConstraint


db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum('student', 'organizer', 'hod', 'admin', name='user_role'),
        nullable=False,
        default='student',
    )
    is_class_incharge = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default='0',
    )

    def __repr__(self):
        return f'<User {self.email}>'


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    venue = db.Column(db.String(150), nullable=False)
    event_date = db.Column(db.DateTime, nullable=False)
    registration_deadline = db.Column(db.DateTime, nullable=False)
    max_participants = db.Column(db.Integer, nullable=False)
    is_intercollege = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    ticket_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0.00, server_default='0.00')
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(
        db.Enum(
            'pending_hod',
            'hod_approved',
            'approved',
            'rejected',
            'completed',
            name='event_status',
        ),
        nullable=False,
        default='pending',
        server_default='pending',
    )

    __table_args__ = (
        CheckConstraint('max_participants > 0', name='max_participants_positive'),
        CheckConstraint('ticket_fee >= 0', name='ticket_fee_non_negative'),
    )

    organizer = db.relationship('User', backref=db.backref('organized_events', lazy=True))
    registrations = db.relationship('Registration', backref='event', lazy=True, cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', backref='event', lazy=True, cascade='all, delete-orphan')
    pa_points = db.relationship('PA_Points', backref='event', uselist=False, cascade='all, delete-orphan')


class Registration(db.Model):
    __tablename__ = 'registrations'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    registered_at = db.Column(db.DateTime, default=utc_now)
    status = db.Column(
        db.Enum('pending_teacher', 'approved', 'rejected', name='registration_status'),
        nullable=False,
        default='pending_teacher',
        server_default='pending_teacher',
    )
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    teacher_note = db.Column(db.String(500), nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'event_id', name='uq_user_event_registration'),)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('event_registrations', lazy=True))
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref=db.backref('reviewed_registrations', lazy=True))


class GeoVerification(db.Model):
    """A cross-match result between the campus and a captured geolocation."""

    __tablename__ = 'geo_verifications'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    source = db.Column(
        db.Enum('device', 'random_shot', name='verification_source'),
        nullable=False,
        default='device',
        server_default='device',
    )
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    accuracy_m = db.Column(db.Float, nullable=True)
    # A missing or invalid location has no distance or probability to record.
    distance_m = db.Column(db.Float, nullable=True)
    match_probability = db.Column(db.Float, nullable=True)
    verdict = db.Column(
        db.Enum('match', 'mismatch', name='verification_verdict'),
        nullable=False,
    )
    model_version = db.Column(db.String(40), nullable=False)
    campus_name = db.Column(db.String(160), nullable=False)
    campus_latitude = db.Column(db.Float, nullable=False)
    campus_longitude = db.Column(db.Float, nullable=False)
    image_path = db.Column(db.String(255), nullable=True)
    captured_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # --- GPS outcome (authoritative for location) ------------------------
    gps_status = db.Column(db.String(32), nullable=True)
    gps_reason = db.Column(db.String(255), nullable=True)
    gps_boundary_source = db.Column(db.String(16), nullable=True)
    location_captured_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, default=utc_now, nullable=True)

    # --- Image comparison outcome (indicative only) ----------------------
    image_status = db.Column(db.String(32), nullable=True)
    image_similarity = db.Column(db.Float, nullable=True)
    image_best_reference = db.Column(db.String(255), nullable=True)
    image_backend = db.Column(db.String(32), nullable=True)
    image_model_version = db.Column(db.String(64), nullable=True)
    image_reference_count = db.Column(db.Integer, nullable=True)

    # --- Combined decision -----------------------------------------------
    final_decision = db.Column(db.String(32), nullable=True)
    decision_flags = db.Column(db.String(500), nullable=True)
    decision_rationale = db.Column(db.Text, nullable=True)

    # --- Human review, kept separate from model suggestions --------------
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    review_decision = db.Column(db.String(32), nullable=True)
    review_note = db.Column(db.String(500), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'event_id', name='uq_user_event_geo_verification'),
        CheckConstraint('latitude >= -90 AND latitude <= 90', name='verification_latitude_check'),
        CheckConstraint(
            'longitude >= -180 AND longitude <= 180', name='verification_longitude_check'
        ),
    )

    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('geo_verifications', lazy=True),
    )
    reviewer = db.relationship(
        'User',
        foreign_keys=[reviewed_by_id],
        backref=db.backref('reviewed_verifications', lazy=True),
    )
    event = db.relationship(
        'Event',
        foreign_keys=[event_id],
        backref=db.backref('geo_verifications', lazy=True, cascade='all, delete-orphan'),
    )


class Feedback(db.Model):
    __tablename__ = 'feedback'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comments = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint('event_id', 'user_id', name='uq_event_user_feedback'),
        CheckConstraint('rating >= 1 AND rating <= 5', name='rating_check'),
    )

    user = db.relationship('User', backref=db.backref('feedback_entries', lazy=True))


class PA_Points(db.Model):
    __tablename__ = 'pa_points'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, unique=True)
    base_points = db.Column(db.Integer, default=10)
    bonus_participants = db.Column(db.Integer, default=0)
    bonus_feedback = db.Column(db.Integer, default=0)
    bonus_intercollege = db.Column(db.Integer, default=0)
    total_points = db.Column(db.Integer, nullable=False)


class ReportRecord(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    generated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    generated_on = db.Column(db.DateTime, default=utc_now)
    file_path = db.Column(db.String(255), nullable=False)

    user = db.relationship('User', backref=db.backref('generated_reports', lazy=True))
