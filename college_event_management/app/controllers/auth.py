import re
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_bcrypt import check_password_hash, generate_password_hash
from sqlalchemy.exc import IntegrityError

from app.models import User, db


auth_bp = Blueprint('auth', __name__)
EMAIL_PATTERN = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')


def get_dashboard_route_for_role(role):
    return {
        'admin': '/admin/dashboard',
        'hod': '/hod/dashboard',
        'organizer': '/organizer/dashboard',
        'student': '/student/dashboard',
    }.get(role, '/student/dashboard')


def role_required(*roles):
    def decorator(func):
        @wraps(func)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(get_dashboard_route_for_role(current_user.role))
            return func(*args, **kwargs)
        return wrapped
    return decorator


def _password_hash_matches(user, password):
    try:
        return bool(user and check_password_hash(user.password_hash, password))
    except (TypeError, ValueError):
        return False


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student')
        allowed_roles = {'student', 'organizer'}

        if not name or not email or not password:
            flash('Please complete all fields.', 'danger')
            return render_template('register.html', role=role, name=name, email=email)

        if role not in allowed_roles:
            flash('Account registration is only available for students and organizers.', 'danger')
            return render_template('register.html', role='student', name=name, email=email)

        if len(name) > 120 or not EMAIL_PATTERN.fullmatch(email) or len(email) > 120:
            flash('Please enter a valid name and email address.', 'danger')
            return render_template('register.html', role=role, name=name, email=email)

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('register.html', role=role, name=name, email=email)

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash('This email is already registered. Please use a different email address.', 'danger')
            return render_template('register.html', role=role, name=name, email=email)

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password).decode('utf-8'),
            role=role,
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('This email is already registered. Please use a different email address.', 'danger')
            return render_template('register.html', role=role, name=name, email=email)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if _password_hash_matches(user, password):
            login_user(user)
            flash(f'Welcome back, {user.name}.', 'success')
            return redirect(get_dashboard_route_for_role(user.role))

        flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Authenticate an existing administrator; provisioning is CLI-only."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email, role='admin').first()

        if _password_hash_matches(user, password):
            login_user(user)
            flash('Welcome back, Administrator.', 'success')
            return redirect(url_for('admin.dashboard'))

        flash('Invalid administrator credentials.', 'danger')

    return render_template('admin_login.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if email:
            flash(
                'Password recovery is not enabled in this build. Please contact the CampusPulse administrator.',
                'info',
            )
            return redirect(url_for('auth.login'))
        flash('Please enter your email address.', 'warning')
    return render_template('forgot_password.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    was_admin = current_user.role == 'admin'
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('landing_page') if was_admin else url_for('auth.login'))
