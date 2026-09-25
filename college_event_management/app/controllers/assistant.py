"""Website-specific assistant for CampusPulse.

The assistant deliberately keeps its knowledge on the server.  It answers from a
curated CampusPulse knowledge base, using lightweight retrieval so the feature
works in the desktop/offline build without requiring an external API key.
"""

import re
from difflib import SequenceMatcher

from flask import Blueprint, jsonify, request, url_for


assistant_bp = Blueprint('assistant', __name__)

MAX_QUESTION_LENGTH = 800
MAX_HISTORY_ITEMS = 6
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'can', 'do', 'for', 'from',
    'how', 'i', 'in', 'is', 'it', 'me', 'my', 'of', 'on', 'or', 'the', 'to',
    'what', 'when', 'where', 'which', 'who', 'why', 'with', 'you', 'your',
}


def _normalise(value):
    value = str(value or '').lower().replace('’', "'")
    value = re.sub(r'[^a-z0-9\s]', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _tokens(value):
    return {
        token for token in TOKEN_PATTERN.findall(_normalise(value))
        if token not in STOP_WORDS and len(token) > 1
    }


# Each entry is intentionally written in user-facing language.  Links are
# endpoint names, not arbitrary URLs, so the client never needs to render
# server-provided HTML or follow an untrusted destination.
KNOWLEDGE_BASE = (
    {
        'id': 'overview',
        'phrases': (
            'what is campuspulse', 'what does campuspulse do', 'tell me about this website',
            'what is this site', 'about campuspulse',
        ),
        'keywords': ('campuspulse', 'platform', 'overview', 'college', 'event', 'participation', 'pa'),
        'answer': (
            'CampusPulse is a college event-management platform. It brings students, '
            'organizers, and administrators together to plan events, manage registrations, '
            'track participation, collect feedback, calculate PA points, and export reports. '
            'The workflow includes students, organizers, HoD verification, and final admin approval.'
        ),
        'links': (('landing_page', 'Explore the homepage'), ('how_to_use', 'Read the user guide')),
    },
    {
        'id': 'create_account',
        'phrases': (
            'create an account', 'create account', 'register an account', 'sign up',
            'signup', 'new user', 'how do i join', 'how to register on the website',
        ),
        'keywords': ('account', 'register', 'registration', 'sign', 'join', 'name', 'email', 'password', 'student', 'organizer'),
        'answer': (
            'Select Create Account, enter your full name and a unique email address, choose '
            'Student or Organizer, and enter a password with at least eight characters. '
            'Admin accounts are not created through the public registration form.'
        ),
        'links': (('auth.register', 'Open registration'), ('how_to_use', 'See the registration guide')),
    },
    {
        'id': 'login',
        'phrases': (
            'how do i log in', 'how to login', 'log in', 'login', 'sign in',
            'cannot login', 'cant login', 'wrong password',
        ),
        'keywords': ('login', 'log', 'sign', 'email', 'password', 'account', 'session', 'dashboard'),
        'answer': (
            'Use the standard Login page for student and organizer accounts. Enter the email '
            'and password you registered with, then CampusPulse will open the dashboard for '
            'your role. Administrators use the separate Admin Login page.'
        ),
        'links': (('auth.login', 'Open Login'), ('auth.admin_login', 'Open Admin Login')),
    },
    {
        'id': 'roles',
        'phrases': (
            'what are the roles', 'student organizer admin', 'who can use the website',
            'what can each role do', 'roles in campuspulse',
        ),
        'keywords': ('role', 'student', 'organizer', 'administrator', 'admin', 'permission', 'account'),
        'answer': (
            'Students browse approved events, register, cancel before deadlines, and provide '
            'feedback. Organizers create events and manage their own event lifecycle. The HoD '
            'verifies program details and forwards approved programs to the administrator. '
            'Administrators provide final approval, calculate PA points, and export reports.'
        ),
        'links': (('how_to_use', 'Read the role guide'), ('auth.register', 'Choose a role')),
    },
    {
        'id': 'class_incharge',
        'phrases': (
            'class incharge', 'class teacher', 'organizer profile', 'am i a class incharge',
            'change organizer role', 'set class incharge status',
        ),
        'keywords': ('class', 'incharge', 'teacher', 'profile', 'organizer', 'status'),
        'answer': (
            'Open your Organizer Dashboard and use the Organizer profile card. In the Class '
            'incharge dropdown choose Yes or No, then select Save. This status is saved to your '
            'organizer account and does not change your event approval permissions.'
        ),
        'links': (('organizer.dashboard', 'Open Organizer Dashboard'), ('how_to_use', 'Read the organizer guide')),
    },
    {
        'id': 'create_event',
        'phrases': (
            'create an event', 'create event', 'add an event', 'organizer event', 'submit an event',
            'how do i host an event', 'new event',
        ),
        'keywords': ('event', 'organizer', 'create', 'submit', 'venue', 'deadline', 'participants', 'intercollege', 'fee'),
        'answer': (
            'Sign in as an Organizer, open Dashboard, and choose New Event. Provide a title, '
            'description, venue, event date, registration deadline, participant limit, and '
            'optional intercollege or paid-event settings. The event is submitted as Awaiting '
            'HoD verification. After the HoD verifies it, the program is sent to the administrator '
            'for final approval and becomes visible to students only after that approval.'
        ),
        'links': (('organizer.dashboard', 'Open Organizer Dashboard'), ('how_to_use', 'Read the organizer guide')),
    },
    {
        'id': 'event_approval',
        'phrases': (
            'how does event approval work', 'approve event', 'event review', 'pending event',
            'why is my event pending', 'reject event', 'admin review',
        ),
        'keywords': ('event', 'approve', 'approval', 'reject', 'review', 'pending', 'status', 'admin'),
        'answer': (
            'Every new organizer event starts as Awaiting HoD verification. The HoD checks the '
            'program details and either rejects it or forwards it to the administrator. Only '
            'after the administrator gives final approval does the event become visible to students.'
        ),
        'links': (('organizer.dashboard', 'View your events'), ('how_to_use', 'Read the admin workflow')),
    },
    {
        'id': 'register_event',
        'phrases': (
            'register for an event', 'register event', 'join an event', 'how do i participate',
            'student event registration', 'sign up for an event',
        ),
        'keywords': ('student', 'event', 'register', 'registration', 'join', 'seat', 'available', 'participate'),
        'answer': (
            'Open the Student Dashboard and choose Register on an approved upcoming event. '
            'Registration is allowed only before the registration deadline and while seats '
            'remain. Each student can register once for a particular event.'
        ),
        'links': (('auth.login', 'Open Student Login'), ('how_to_use', 'Read the student guide')),
    },
    {
        'id': 'cancel_event',
        'phrases': (
            'cancel an event registration', 'cancel registration', 'unregister', 'remove me from event',
            'cancel my event',
        ),
        'keywords': ('cancel', 'registration', 'unregister', 'event', 'deadline', 'student'),
        'answer': (
            'Open the Student Dashboard, find the event in your registrations, and choose '
            'Cancel. Cancellation is available before the event registration deadline; after '
            'that, contact the organizer or administrator.'
        ),
        'links': (('auth.login', 'Open Student Login'), ('how_to_use', 'Read the student guide')),
    },
    {
        'id': 'payment',
        'phrases': (
            'how do i pay', 'payment for event', 'pay for an event', 'ticket fee',
            'paid event', 'event payment',
        ),
        'keywords': ('payment', 'pay', 'paid', 'fee', 'ticket', 'money', 'free'),
        'answer': (
            'Free events do not require payment. For a paid event, the Student Dashboard shows '
            'the ticket fee and a payment-information link after registration. CampusPulse does '
            'not process or verify online payments, so contact the event organizer for approved '
            'payment instructions and keep your receipt.'
        ),
        'links': (('auth.login', 'Open Student Dashboard'), ('how_to_use', 'Read the payment guidance')),
    },
    {
        'id': 'feedback',
        'phrases': (
            'submit feedback', 'give feedback', 'event rating', 'rate an event', 'feedback form',
            'how do i give feedback', 'comments about an event',
        ),
        'keywords': ('feedback', 'rating', 'rate', 'comment', 'completed', 'event', 'student'),
        'answer': (
            'Feedback is intended for students after an organizer marks the event Completed. '
            'A student can submit one rating from 1 to 5 and optional comments. If a completed '
            'event is not showing a feedback control, contact the organizer or administrator; '
            'the dashboard may need the event to be displayed for your account.'
        ),
        'links': (('auth.login', 'Open Student Login'), ('how_to_use', 'Read the feedback guide')),
    },
    {
        'id': 'pa_points',
        'phrases': (
            'how are pa points calculated', 'pa point calculation', 'pa scoring', 'how many pa points',
            'pa points formula', 'what is pa',
        ),
        'keywords': ('pa', 'point', 'points', 'score', 'scoring', 'bonus', 'participant', 'feedback', 'intercollege'),
        'answer': (
            'The scoring starts with 10 base points. CampusPulse adds 2 points when an event '
            'has more than 50 participants, 3 points when the average feedback rating is at '
            'least 4.0, and 5 points for an intercollege event. The maximum calculated score '
            'is 20 points. An administrator calculates the score from the event dashboard.'
        ),
        'links': (('auth.admin_login', 'Open Admin Login'), ('how_to_use', 'Read the PA guide')),
    },
    {
        'id': 'reports',
        'phrases': (
            'how do i download a report', 'export report', 'pdf report', 'excel report',
            'generate report', 'report format', 'download pa report',
        ),
        'keywords': ('report', 'export', 'download', 'pdf', 'excel', 'xlsx', 'academic', 'admin', 'document'),
        'answer': (
            'An administrator can select a completed event and export its PA information as a '
            'PDF or Excel workbook. Reports include event details, the scoring breakdown, and '
            'the generated academic-year summary. Open the Admin Dashboard and use the report '
            'action beside the relevant event.'
        ),
        'links': (('auth.admin_login', 'Open Admin Login'), ('how_to_use', 'Read the reports guide')),
    },
    {
        'id': 'hod_review',
        'phrases': (
            'hod dashboard', 'head of department', 'hod approval', 'verify program',
            'send program to admin', 'hod review',
        ),
        'keywords': ('hod', 'department', 'head', 'verify', 'review', 'forward', 'admin', 'program'),
        'answer': (
            'The HoD signs in with a provisioned HoD account and opens the HoD Dashboard. '
            'Review the program title, description, venue, schedule, capacity, fee, and organizer. '
            'Choose Verify & send to admin after the details are correct, or Reject if they are not.'
        ),
        'links': (('hod.dashboard', 'Open HoD Dashboard'), ('how_to_use', 'Read the HoD guide')),
    },
    {
        'id': 'admin',
        'phrases': (
            'what can an admin do', 'administrator dashboard', 'admin functions',
            'how do i review events', 'admin help',
        ),
        'keywords': ('admin', 'administrator', 'dashboard', 'review', 'approve', 'reject', 'calculate', 'report', 'manage'),
        'answer': (
            'Administrators provide final approval for programs that the HoD has already verified, '
            'calculate PA points, and export PDF or Excel reports. Use the separate Admin Login, '
            'then open the Admin Dashboard. The admin can act on programs marked Awaiting Final Approval.'
        ),
        'links': (('auth.admin_login', 'Open Admin Login'), ('how_to_use', 'Read the admin guide')),
    },
    {
        'id': 'password_reset',
        'phrases': (
            'forgot password', 'reset my password', 'change password', 'recover account',
            'password reset', 'cannot remember password',
        ),
        'keywords': ('forgot', 'reset', 'recover', 'password', 'account', 'email', 'login'),
        'answer': (
            'The website currently has a Forgot Password page, but it does not yet send a real '
            'reset email or provide a password-reset link. Until password recovery is enabled, '
            'contact the website administrator or the person who manages your CampusPulse account.'
        ),
        'links': (('auth.forgot_password', 'Open Forgot Password'), ('how_to_use', 'Read account help')),
    },
    {
        'id': 'event_not_visible',
        'phrases': (
            'why can i not see an event', 'event is missing', 'no events showing',
            'why is my event not visible', 'event disappeared', 'dashboard is empty',
        ),
        'keywords': ('event', 'visible', 'missing', 'show', 'dashboard', 'approved', 'pending', 'rejected', 'completed', 'past'),
        'answer': (
            'Students only see approved, upcoming events. Check that the event is approved, '
            'its event date has not passed, and you are signed into the correct account. An '
            'organizer should check Awaiting HoD, Awaiting Final Approval, or Rejected status in the Organizer Dashboard. '
            'A completed event may no longer appear in the active-event list.'
        ),
        'links': (('auth.login', 'Open your dashboard'), ('how_to_use', 'Read the event guide')),
    },
    {
        'id': 'dashboard_metrics',
        'phrases': (
            'why are the dashboard numbers zero', 'dashboard count', 'open for registration count',
            'registered events count', 'summary cards',
        ),
        'keywords': ('dashboard', 'count', 'number', 'zero', 'metric', 'card', 'registered', 'open'),
        'answer': (
            'Dashboard cards summarize the records visible to the current account. The student '
            'card covers approved upcoming events, while registrations include the account history. '
            'If a number looks stale, refresh the dashboard and verify the event status, deadline, '
            'and account role. Organizer summary cards can also be empty when no matching events exist.'
        ),
        'links': (('auth.login', 'Open your dashboard'), ('how_to_use', 'Read the dashboard guide')),
    },
    {
        'id': 'data_storage',
        'phrases': (
            'where is my data stored', 'database', 'is my data online', 'backup', 'sync',
            'where are reports saved', 'local data',
        ),
        'keywords': ('data', 'database', 'stored', 'storage', 'online', 'cloud', 'sync', 'backup', 'report', 'local'),
        'answer': (
            'The local desktop version uses a local SQLite database beside the application or '
            'executable, and generated reports are stored in the application report directory. '
            'CampusPulse does not provide cloud synchronization in this build. Keep regular '
            'backups of the database and report files if you need to preserve activity.'
        ),
        'links': (('how_to_use', 'Read the user guide'),),
    },
    {
        'id': 'offline',
        'phrases': (
            'does it work offline', 'internet connection', 'desktop app', 'offline mode',
            'why is the styling missing', 'cdn', 'webview',
        ),
        'keywords': ('offline', 'internet', 'connection', 'desktop', 'browser', 'style', 'bootstrap', 'network', 'webview'),
        'answer': (
            'CampusPulse can be opened in its desktop or local browser mode, but the interface '
            'loads Bootstrap styling and scripts from a public CDN. For a completely offline '
            'experience, those frontend assets should be bundled locally. Your local database '
            'continues to work when the app is running locally.'
        ),
        'links': (('how_to_use', 'Read the getting-started guide'),),
    },
    {
        'id': 'security',
        'phrases': (
            'is my password safe', 'how are passwords stored', 'security', 'privacy',
            'is my data encrypted', 'safe to use', 'account security',
        ),
        'keywords': ('password', 'secure', 'security', 'privacy', 'encrypted', 'hashed', 'data', 'safe', 'bcrypt'),
        'answer': (
            'Normal account passwords are hashed with bcrypt rather than stored as plain text. '
            'Still, use a unique password, do not share credentials, and avoid entering sensitive '
            'information into unofficial messages. This local build is intended for controlled '
            'use; a public deployment should add rate limiting, secure cookies, and HTTPS.'
        ),
        'links': (('how_to_use', 'Read security guidance'), ('auth.login', 'Open Login')),
    },
    {
        'id': 'logout',
        'phrases': ('how do i log out', 'logout', 'log out', 'sign out', 'close account'),
        'keywords': ('log', 'logout', 'sign', 'out', 'session', 'exit'),
        'answer': (
            'Select Logout in the top navigation while you are signed in. This ends your '
            'CampusPulse session and returns you to the public sign-in options.'
        ),
        'links': (('auth.login', 'Open Login'),),
    },
    {
        'id': 'manual',
        'phrases': (
            'how to use campuspulse', 'user guide', 'where is the manual', 'help guide',
            'show me the instructions', 'how to use the website',
        ),
        'keywords': ('manual', 'guide', 'instructions', 'help', 'documentation', 'use', 'tutorial'),
        'answer': (
            'The How-To-Use page is the step-by-step guide for students, organizers, and '
            'administrators. It explains registration, event creation, approvals, student '
            'registration, feedback, PA scoring, reports, and account actions.'
        ),
        'links': (('how_to_use', 'Open How-To-Use'),),
    },
    {
        'id': 'capabilities',
        'phrases': (
            'what can you answer', 'what can you do', 'are you ai', 'how do you work',
            'what topics do you cover', 'help assistant',
        ),
        'keywords': ('assistant', 'answer', 'question', 'help', 'website', 'topic', 'support', 'chat'),
        'answer': (
            'I am the CampusPulse website assistant. I can explain accounts, roles, event '
            'creation and approval, student registration, deadlines, capacity, payment policy, '
            'feedback, PA points, reports, security, local storage, and troubleshooting. I can '
            'guide you to the right page, but I cannot change account or event data for you.'
        ),
        'links': (('how_to_use', 'Open the complete guide'), ('landing_page', 'Return home')),
    },
    {
        'id': 'support',
        'phrases': (
            'contact support', 'talk to a human', 'report a problem', 'who do i contact',
            'website issue', 'complaint', 'help agent',
        ),
        'keywords': ('contact', 'support', 'human', 'agent', 'problem', 'issue', 'complaint', 'help', 'administrator'),
        'answer': (
            'If the website or app crashes, contact Edwin J Anil (Developer) at '
            'edwinjanil5@gmail.com or 8138815144. Include the page you were using and the '
            'action that failed, but never share your password.'
        ),
        'links': (('contact', 'View support details'), ('how_to_use', 'Open the user guide')),
    },
)


_INDEX = tuple((entry, _tokens(' '.join(entry['phrases'] + entry['keywords']))) for entry in KNOWLEDGE_BASE)


def _entry_score(message, entry, entry_tokens):
    normalised = _normalise(message)
    query_tokens = _tokens(message)
    score = 0.0

    for phrase in entry['phrases']:
        if phrase in normalised:
            score += 18.0 + min(len(phrase), 30) / 10.0
        else:
            ratio = SequenceMatcher(None, normalised, phrase).ratio()
            if ratio >= 0.62:
                score += ratio * 5.0

    for keyword in entry['keywords']:
        keyword_normalised = _normalise(keyword)
        if ' ' in keyword_normalised:
            if keyword_normalised in normalised:
                score += 7.0
        elif keyword_normalised in query_tokens:
            score += 5.0
        elif len(keyword_normalised) > 4 and keyword_normalised in normalised:
            score += 2.0

    score += len(query_tokens & entry_tokens) * 1.4
    return score


def _special_response(message):
    normalised = _normalise(message)
    tokens = _tokens(normalised)
    if not tokens or len(tokens) <= 3 and normalised in {'hi', 'hello', 'hey', 'hii', 'helo'}:
        return (
            'Hello! I can help you navigate CampusPulse. Ask about accounts, events, '
            'registrations, payments, feedback, PA points, reports, or a problem you are facing.'
        )
    if normalised in {'thanks', 'thank you', 'thanks a lot', 'thankyou'}:
        return 'You are welcome. If another part of CampusPulse is unclear, ask me again.'
    if 'who made you' in normalised or 'who are you' in normalised or 'what are you' in normalised:
        return (
            'I am the CampusPulse website assistant. I use the website guide and CampusPulse '
            'workflows to give you accurate step-by-step help.'
        )
    return None


def _links_for(entry):
    links = []
    for endpoint, label in entry.get('links', ()):
        try:
            links.append({'label': label, 'url': url_for(endpoint)})
        except Exception:
            # A link is helpful but should never make the assistant fail.
            continue
    return links


def _history_text(history):
    if not isinstance(history, list):
        return ''
    recent = []
    for item in history[-MAX_HISTORY_ITEMS:]:
        if not isinstance(item, dict) or item.get('role') != 'user':
            continue
        value = item.get('content', item.get('message', ''))
        if isinstance(value, str):
            recent.append(value[:240])
    return ' '.join(recent)


def _find_response(message, history=''):
    special = _special_response(message)
    if special:
        return {
            'answer': special,
            'suggestions': [
                {'label': 'View the guide', 'url': url_for('how_to_use')},
                {'label': 'Create an account', 'url': url_for('auth.register')},
            ],
            'topic': 'conversation',
        }

    # A short follow-up such as "how do I do that?" benefits from the most
    # recent user turn, while a complete new question remains independent.
    search_message = message
    if len(_tokens(message)) < 4 and history:
        search_message = f'{history} {message}'

    ranked = sorted(
        ((_entry_score(search_message, entry, entry_tokens), entry) for entry, entry_tokens in _INDEX),
        key=lambda pair: (-pair[0], pair[1]['id']),
    )
    best_score, best_entry = ranked[0]

    if best_score < 4.0:
        suggestions = [
            {'label': 'How do I register for an event?', 'url': url_for('auth.login')},
            {'label': 'How are PA points calculated?', 'url': url_for('how_to_use')},
            {'label': 'How do I create an event?', 'url': url_for('organizer.dashboard')},
        ]
        return {
            'answer': (
                'I could not find a specific CampusPulse answer for that question. I can help '
                'with accounts, roles, event creation and approval, registrations, deadlines, '
                'capacity, payment policy, feedback, PA points, reports, security, local storage, '
                'and troubleshooting. Try rephrasing it with one of those topics.'
            ),
            'suggestions': suggestions,
            'topic': 'fallback',
        }

    suggestion_entries = [entry for score, entry in ranked if score >= max(4.0, best_score * 0.45)][:3]
    suggestions = []
    for entry in suggestion_entries:
        links = _links_for(entry)
        if links:
            suggestions.append(links[0])

    return {
        'answer': best_entry['answer'],
        'suggestions': suggestions,
        'topic': best_entry['id'],
    }


@assistant_bp.route('/ask', methods=['POST'])
def ask():
    """Answer a website question without exposing a provider key to the browser."""
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {'message': request.form.get('message', '')}
    if not isinstance(payload, dict):
        return jsonify({'error': 'Please send a question in JSON format.'}), 400

    message = payload.get('message', '')
    if not isinstance(message, str):
        return jsonify({'error': 'Please enter a question before sending it.'}), 400
    message = message.strip()
    if not message:
        return jsonify({'error': 'Please enter a question before sending it.'}), 400
    if len(message) > MAX_QUESTION_LENGTH:
        return jsonify({'error': f'Please keep your question under {MAX_QUESTION_LENGTH} characters.'}), 400

    try:
        response = _find_response(message, _history_text(payload.get('history', [])))
    except Exception:
        # Keep the public assistant available even if a future knowledge entry
        # is malformed; do not expose implementation details to the client.
        response = {
            'answer': 'I am having trouble looking up that answer right now. Please try one of the common help topics below.',
            'suggestions': [
                {'label': 'Open the user guide', 'url': url_for('how_to_use')},
                {'label': 'Open Login', 'url': url_for('auth.login')},
            ],
            'topic': 'error',
        }

    response['source'] = 'CampusPulse website guide'
    response = jsonify(response)
    response.headers['Cache-Control'] = 'no-store'
    return response
