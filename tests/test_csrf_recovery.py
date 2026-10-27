from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.backend.auth import digest
from database.models import AuthSession, utcnow


@pytest.mark.parametrize('missing', [True, False], ids=['lost-cookie', 'stale-cookie'])
def test_csrf_recovery_preserves_session_and_restores_protected_requests(doctor_client, doctor, db, missing):
    session_id = digest(doctor_client.cookies.get('cc_session'))
    session = db.get(AuthSession, session_id)
    original_token = session.csrf
    if missing:
        doctor_client.cookies.delete('cc_csrf')
    else:
        for cookie in doctor_client.cookies.jar:
            if cookie.name == 'cc_csrf':
                cookie.value = 'obsolete-token'
    assert doctor_client.post('/api/auth/logout').status_code == 403
    recovered = doctor_client.get('/api/auth/csrf')
    assert recovered.status_code == 200
    assert recovered.json()['csrf_token'] == original_token
    assert doctor_client.cookies.get('cc_csrf') == original_token
    assert digest(doctor_client.cookies.get('cc_session')) == session_id
    assert doctor_client.get('/api/auth/me').json()['id'] == doctor.id
    db.refresh(session)
    assert session.csrf == original_token
    doctor_client.headers['X-CSRF-Token'] = recovered.json()['csrf_token']
    assert doctor_client.post('/api/auth/logout', headers={'Origin': 'https://other.invalid'}).status_code == 403
    assert doctor_client.post('/api/auth/logout').status_code == 200
    assert doctor_client.get('/api/auth/me').status_code == 401


def test_csrf_recovery_does_not_revive_expired_session(doctor_client, db):
    session = db.get(AuthSession, digest(doctor_client.cookies.get('cc_session')))
    session.expires_at = utcnow() - timedelta(seconds=1)
    for cookie in doctor_client.cookies.jar:
        if cookie.name == 'cc_csrf':
            cookie.value = 'guest-cookie'
    db.commit()
    assert doctor_client.get('/api/auth/csrf').json()['csrf_token'] == 'guest-cookie'
    assert doctor_client.get('/api/auth/me').status_code == 401
    doctor_client.headers['X-CSRF-Token'] = 'guest-cookie'
    assert doctor_client.post('/api/auth/logout').status_code == 401


def test_guest_csrf_does_not_create_an_authenticated_session(client, db):
    response = client.get('/api/auth/csrf')
    assert response.status_code == 200
    assert response.json()['csrf_token'] == client.cookies.get('cc_csrf')
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert client.get('/api/auth/me').status_code == 401
