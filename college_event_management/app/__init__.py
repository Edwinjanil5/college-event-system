import os
import re
from datetime import timedelta

import click
from flask import Flask, Response, make_response, redirect, render_template, request, session, url_for
from flask_bcrypt import Bcrypt, generate_password_hash
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, generate_csrf

from app.models import User, db
from app.workflow import current_academic_year
from config.settings import Config


PUBLIC_INDEXABLE_PATHS = frozenset({'/', '/how-to-use', '/contact'})
SITE_DESCRIPTION = (
    'CampusPulse is a college event management platform for student registration, '
    'organizer submissions, HoD review, approvals, feedback, PA points, and reports.'
)


login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()
migrate = Migrate()

login_manager.login_view = 'auth.login'
login_manager.session_protection = 'strong'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for('auth.login'))


def _validate_admin_email(email):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email))


def register_cli_commands(app):
    @app.cli.command('create-admin')
    @click.option('--email', prompt='Administrator email')
    @click.option('--name', prompt='Administrator name', default='Administrator', show_default=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(email, name, password):
        """Create the first administrator without storing a default password."""
        email = email.strip().lower()
        name = name.strip()
        if not _validate_admin_email(email):
            raise click.ClickException('Enter a valid administrator email address.')
        if len(name) < 2 or len(name) > 120:
            raise click.ClickException('Administrator name must be between 2 and 120 characters.')
        if len(password) < 12:
            raise click.ClickException('Administrator passwords must be at least 12 characters long.')

        existing = User.query.filter_by(email=email).first()
        if existing is not None:
            if existing.role == 'admin':
                raise click.ClickException('An administrator with that email already exists.')
            raise click.ClickException('That email is already assigned to a non-admin account.')

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password).decode('utf-8'),
            role='admin',
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f'Administrator {email} created successfully.')

    @app.cli.command('reset-admin-password')
    @click.option('--email', prompt='Administrator email')
    @click.password_option(confirmation_prompt=True)
    def reset_admin_password(email, password):
        """Reset an existing administrator password without exposing it in source."""
        email = email.strip().lower()
        if len(password) < 12:
            raise click.ClickException('Administrator passwords must be at least 12 characters long.')
        user = User.query.filter_by(email=email, role='admin').first()
        if user is None:
            raise click.ClickException('No administrator account was found for that email.')
        user.password_hash = generate_password_hash(password).decode('utf-8')
        db.session.commit()
        click.echo(f'Password updated for administrator {email}.')

    @app.cli.command('create-hod')
    @click.option('--email', prompt='HoD email')
    @click.option('--name', prompt='HoD name', default='Head of Department', show_default=True)
    @click.password_option(confirmation_prompt=True)
    def create_hod(email, name, password):
        """Create a HoD account without exposing a default password."""
        email = email.strip().lower()
        name = name.strip()
        if not _validate_admin_email(email):
            raise click.ClickException('Enter a valid HoD email address.')
        if len(name) < 2 or len(name) > 120:
            raise click.ClickException('HoD name must be between 2 and 120 characters.')
        if len(password) < 12:
            raise click.ClickException('HoD passwords must be at least 12 characters long.')

        existing = User.query.filter_by(email=email).first()
        if existing is not None:
            if existing.role == 'hod':
                raise click.ClickException('A HoD with that email already exists.')
            raise click.ClickException('That email is already assigned to another account.')

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password).decode('utf-8'),
            role='hod',
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f'HoD {email} created successfully.')

    @app.cli.command('reset-hod-password')
    @click.option('--email', prompt='HoD email')
    @click.password_option(confirmation_prompt=True)
    def reset_hod_password(email, password):
        """Reset an existing HoD password without exposing it in source."""
        email = email.strip().lower()
        if len(password) < 12:
            raise click.ClickException('HoD passwords must be at least 12 characters long.')
        user = User.query.filter_by(email=email, role='hod').first()
        if user is None:
            raise click.ClickException('No HoD account was found for that email.')
        user.password_hash = generate_password_hash(password).decode('utf-8')
        db.session.commit()
        click.echo(f'Password updated for HoD {email}.')


def create_app(test_config=None):
    app = Flask(__name__, template_folder='views', static_folder='static')
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
    app.config.setdefault('SESSION_COOKIE_SECURE', False)
    app.config.setdefault('REMEMBER_COOKIE_HTTPONLY', True)
    app.config.setdefault('REMEMBER_COOKIE_SAMESITE', 'Lax')
    app.config.setdefault('REMEMBER_COOKIE_SECURE', False)

    db.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    register_cli_commands(app)

    os.makedirs(app.config.get('REPORTS_FOLDER', 'static/uploads'), exist_ok=True)

    # Tests and explicitly configured local instances may opt into automatic
    # table creation. Production/desktop releases use `flask db upgrade` so
    # schema changes are versioned instead of silently mutating an old DB.
    if app.config.get('TESTING') or app.config.get('AUTO_CREATE_DB', False):
        with app.app_context():
            db.create_all()

    from app.controllers.assistant import assistant_bp
    from app.controllers.auth import auth_bp
    from app.controllers.student import student_bp
    from app.controllers.organizer import organizer_bp
    from app.controllers.hod import hod_bp
    from app.controllers.admin import admin_bp
    from app.controllers.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(organizer_bp, url_prefix='/organizer')
    app.register_blueprint(hod_bp, url_prefix='/hod')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(assistant_bp, url_prefix='/assistant')

    @app.before_request
    def set_session_controls():
        session.permanent = True
        app.permanent_session_lifetime = app.config.get(
            'PERMANENT_SESSION_LIFETIME', timedelta(minutes=30)
        )

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        if request.path not in PUBLIC_INDEXABLE_PATHS:
            response.headers.setdefault('X-Robots-Tag', 'noindex, nofollow')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
        )
        return response

    @app.route('/')
    def landing_page():
        return render_template('landing.html')

    @app.route('/how-to-use')
    def how_to_use():
        return render_template('manual.html')

    @app.route('/contact')
    def contact():
        return render_template('contact.html')

    @app.get('/sitemap.xml')
    def sitemap():
        public_urls = [
            url_for('landing_page', _external=True),
            url_for('how_to_use', _external=True),
            url_for('contact', _external=True),
        ]
        entries = ''.join(
            f'<url><loc>{page_url}</loc></url>' for page_url in public_urls
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{entries}</urlset>'
        )
        return Response(body, mimetype='application/xml')

    @app.get('/robots.txt')
    def robots():
        sitemap_url = url_for('sitemap', _external=True)
        body = '\n'.join(
            [
                'User-agent: *',
                'Allow: /',
                'Disallow: /login',
                'Disallow: /register',
                'Disallow: /admin',
                'Disallow: /hod',
                'Disallow: /organizer',
                'Disallow: /student',
                'Disallow: /reports',
                'Disallow: /assistant',
                'Disallow: /health',
                f'Sitemap: {sitemap_url}',
                '',
            ]
        )
        response = make_response(body)
        response.mimetype = 'text/plain'
        return response

    @app.route('/health')
    def health_check():
        try:
            db.session.execute(db.text('SELECT 1'))
            return {'status': 'ok'}, 200
        except Exception:
            app.logger.exception('Database health check failed')
            return {'status': 'error'}, 503

    @app.context_processor
    def inject_template_helpers():
        return {
            'csrf_token': generate_csrf,
            'academic_year': current_academic_year(),
            'support_name': app.config['SUPPORT_NAME'],
            'support_role': app.config['SUPPORT_ROLE'],
            'support_email': app.config['SUPPORT_EMAIL'],
            'support_phone': app.config['SUPPORT_PHONE'],
        }

    return app
