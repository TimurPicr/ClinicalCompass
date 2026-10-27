from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.backend.core.config import settings
from app.backend.core.time import report_date
from app.backend.models.clinical import DiaryEntry, DiaryRevision, Invitation, QuestionnaireResult
from app.backend.services.mail import send_invitation


def test_diary_saved_by_calendar_date_and_revised(patient_client, doctor_client, actors, db_factory):
    pid = actors['patient'].id
    day = (report_date() - timedelta(days=2)).isoformat()
    payload = {'entry_date': day, 'answers': [1, 2, 3, 1, 0], 'text': 'Синтетическая запись дня'}
    first = patient_client.post(f'/api/patients/{pid}/diary', json=payload)
    assert first.status_code == 200, first.text
    first = first.json()
    assert first['entry_date'] == day and first['score'] == 7
    unchanged = patient_client.post(f'/api/patients/{pid}/diary', json=payload).json()
    assert unchanged['result_id'] == first['result_id']
    edited = patient_client.post(f'/api/patients/{pid}/diary', json={**payload, 'text': 'Правка дневника'}).json()
    assert edited['result_id'] == first['result_id']
    changed_score = patient_client.post(f'/api/patients/{pid}/diary', json={**payload, 'answers': [0]*5}).json()
    assert changed_score['score'] == 0 and changed_score['id'] == first['id']
    rows = doctor_client.get(f'/api/patients/{pid}/diary').json()
    assert len(rows) == 1 and rows[0]['score'] == 0
    series = doctor_client.get(f'/api/patients/{pid}/diary/series').json()
    assert series[0]['points'][0]['at'].startswith(day)
    assert len(series[0]['points']) == 1
    revisions = doctor_client.get(f"/api/patients/{pid}/diary/{first['id']}/revisions").json()
    assert len(revisions) == 3 and revisions[0]['text'] == payload['text']
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(DiaryEntry)) == 1
        assert db.scalar(select(func.count()).select_from(QuestionnaireResult)) == 2
        assert db.scalar(select(func.count()).select_from(DiaryRevision)) == 3


def test_diary_guards_dates_and_filters(patient_client, doctor_client, actors):
    pid, foreign = actors['patient'].id, actors['otherpatient'].id
    payload = {'entry_date': report_date().isoformat(), 'answers': [0]*5, 'text': ''}
    assert patient_client.post(f'/api/patients/{foreign}/diary', json=payload).status_code == 404
    assert doctor_client.post(f'/api/patients/{pid}/diary', json=payload).status_code == 403
    for suffix in ['diary', 'diary/series', 'diary/1/revisions']:
        assert doctor_client.get(f'/api/patients/{foreign}/{suffix}').status_code == 404
        assert patient_client.get(f'/api/patients/{foreign}/{suffix}').status_code == 404
    for invalid in [{**payload, 'entry_date': '2999-01-01'}, {**payload, 'answers': [True]*5}, {**payload, 'answers': [5]*5}]:
        assert patient_client.post(f'/api/patients/{pid}/diary', json=invalid).status_code == 422
    assert patient_client.get(f'/api/patients/{pid}/diary?start=2026-10-22&end=2026-01-01').status_code == 422
    assert patient_client.post(f'/api/patients/{pid}/diary', json=payload).status_code == 200
    assert patient_client.get(f'/api/patients/{pid}/diary?end=2000-01-01').json() == []


def test_email_invite_response_and_failure_rollback(doctor_client, mailbox, monkeypatch, db_factory):
    response = doctor_client.post('/api/invitations', json={'email': 'recipient@example.com'})
    assert response.status_code == 201
    assert response.json()['delivery_status'] == 'sent' and 'token' not in response.json()
    assert mailbox[0]['email'] == 'recipient@example.com'
    def fail(email, token):
        raise HTTPException(502, 'Почта недоступна')
    monkeypatch.setattr('app.backend.api.patients.send_invitation', fail)
    assert doctor_client.post('/api/invitations', json={'email': 'failed@example.com'}).status_code == 502
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(Invitation)) == 1


def test_smtp_message_contains_accept_link(monkeypatch):
    monkeypatch.setattr(settings, 'smtp_host', 'mailpit')
    monkeypatch.setattr(settings, 'smtp_port', 1025)
    monkeypatch.setattr(settings, 'smtp_security', 'none')
    monkeypatch.setattr(settings, 'smtp_username', '')
    monkeypatch.setattr(settings, 'public_app_url', 'http://localhost:5173')
    server = MagicMock()
    server.send_message.return_value = {}
    connection = MagicMock()
    connection.__enter__.return_value = server
    monkeypatch.setattr('app.backend.services.mail.smtplib.SMTP', lambda *args, **kwargs: connection)
    send_invitation('recipient@example.com', 'test-token-123')
    message = server.send_message.call_args.args[0]
    assert message['To'] == 'recipient@example.com'
    assert 'http://localhost:5173/#invite=test-token-123' in message.get_body(preferencelist=('plain',)).get_content()
    assert 'Принять приглашение' in message.get_body(preferencelist=('html',)).get_content()
    server.starttls.assert_not_called()


def test_smtp_configuration_and_delivery_errors(monkeypatch):
    monkeypatch.setattr(settings, 'smtp_host', '')
    with pytest.raises(HTTPException) as error:
        send_invitation('test@example.com', 'token')
    assert error.value.status_code == 503
    monkeypatch.setattr(settings, 'smtp_host', 'smtp.example.com')
    monkeypatch.setattr(settings, 'smtp_security', 'starttls')
    monkeypatch.setattr('app.backend.services.mail.smtplib.SMTP', MagicMock(side_effect=OSError('private diagnostic')))
    with pytest.raises(HTTPException) as error:
        send_invitation('test@example.com', 'token')
    assert error.value.status_code == 502 and 'private diagnostic' not in error.value.detail


def test_chat_incremental_delivery(patient_client, doctor_client, actors):
    pid = actors['patient'].id
    first = patient_client.post(f'/api/patients/{pid}/messages', json={'text': 'Первое'}).json()
    second = doctor_client.post(f'/api/patients/{pid}/messages', json={'text': 'Ответ'}).json()
    assert patient_client.get(f"/api/patients/{pid}/messages?after_id={first['id']}").json() == [second]
    assert patient_client.get(f"/api/patients/{pid}/messages?after_id={second['id']}").json() == []
    assert patient_client.get(f'/api/patients/{pid}/messages?after_id=-1').status_code == 422
