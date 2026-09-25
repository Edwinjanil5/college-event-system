from app import create_app
from app.models import db


def test_assistant_answers_website_workflow_questions(client):
    response = client.post('/assistant/ask', json={'message': 'How are PA points calculated?'})
    assert response.status_code == 200
    payload = response.get_json()
    assert '10 base points' in payload['answer']
    assert payload['source'] == 'CampusPulse website guide'
    assert payload['topic'] == 'pa_points'
    assert payload['suggestions']


def test_assistant_explains_class_incharge_setting(client):
    response = client.post('/assistant/ask', json={'message': 'How do I set my class incharge status?'})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['topic'] == 'class_incharge'
    assert 'Organizer profile' in payload['answer']


def test_assistant_has_safe_fallback_for_unknown_question(client):
    response = client.post('/assistant/ask', json={'message': 'What is the capital of an unrelated planet?'})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['topic'] == 'fallback'
    assert 'CampusPulse' in payload['answer']


def test_assistant_validates_question_length(client):
    response = client.post('/assistant/ask', json={'message': 'x' * 801})
    assert response.status_code == 400
    assert '800' in response.get_json()['error']


def test_assistant_accepts_csrf_header_for_json_requests():
    app = create_app(
        {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite://',
            'WTF_CSRF_ENABLED': True,
        }
    )
    with app.app_context():
        db.create_all()
    client = app.test_client()
    page = client.get('/')
    token = page.get_data(as_text=True).split('name="csrf-token" content="', 1)[1].split('"', 1)[0]

    response = client.post(
        '/assistant/ask',
        json={'message': 'How do I register for an event?'},
        headers={'X-CSRFToken': token},
    )
    assert response.status_code == 200
