from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.backend.core.config import settings
from app.backend.core.time import report_date
from app.backend.core.security import digest
from app.backend.models.clinical import AuthSession, Invitation, QuestionnaireResult, AuditEvent
from app.backend.models.user import User
from conftest import PASSWORD, signed_in


def post(client, url, data=None, status=200):
    response = client.post(url, json=data or {})
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def create_plan(doctor, patient_id, **extra):
    return post(doctor, f"/api/patients/{patient_id}/plans",
                {"title": "Синтетический план наблюдения", "instructions": "Пройти учебный опрос", **extra}, 201)


def test_registration_login_and_logout(client, db_factory):
    data = {"email": "new@example.com", "full_name": "Синтетический пациент", "password": PASSWORD}
    assert post(client, '/api/auth/register', data, 201)['role'] == 'patient'
    post(client, '/api/auth/register', data, 409)
    post(client, '/api/auth/register', {**data, 'email': 'doctor-hack@example.com', 'role': 'doctor'}, 422)
    post(client, '/api/auth/login', {"email": data['email'], 'password': 'wrong'}, 401)
    post(client, '/api/auth/login', {'email': data['email'], 'password': PASSWORD})
    token = client.cookies.get('cc_session')
    assert 'HttpOnly' in client.cookies.jar._cookies['testserver.local']['/']['cc_session']._rest
    client.headers['X-CSRF-Token'] = client.cookies.get('cc_csrf')
    assert client.get('/api/auth/me').json()['email'] == data['email']
    with db_factory() as db:
        user = db.scalar(select(User).where(User.email == data['email']))
        assert user.password_hash.startswith('$argon2id$') and user.password_hash != PASSWORD
    post(client, '/api/auth/logout', status=204)
    client.cookies.set('cc_session', token)
    assert client.get('/api/auth/me').status_code == 401


def test_doctor_and_patient_sessions_work_independently(doctor_client, patient_client, actors):
    pid = actors['patient'].id
    assert doctor_client.get('/api/auth/me').json()['id'] == actors['doctor'].id
    assert patient_client.get('/api/auth/me').json()['id'] == pid

    post(doctor_client, f'/api/patients/{pid}/messages', {'text': 'Вопрос врача'}, 201)
    post(patient_client, f'/api/patients/{pid}/messages', {'text': 'Ответ пациента'}, 201)
    conversation = patient_client.get(f'/api/patients/{pid}/messages').json()
    assert [message['sender_id'] for message in conversation] == [actors['doctor'].id, pid]
    assert conversation == doctor_client.get(f'/api/patients/{pid}/messages').json()

    # A token copied from another browser session cannot authorize a mutation.
    response = patient_client.post(f'/api/patients/{pid}/messages', json={'text': 'Чужой токен'},
                                   headers={'X-CSRF-Token': doctor_client.cookies.get('cc_csrf')})
    assert response.status_code == 403

    post(doctor_client, '/api/auth/logout', status=204)
    assert doctor_client.get('/api/auth/me').status_code == 401
    assert patient_client.get('/api/auth/me').json()['id'] == pid
    post(patient_client, f'/api/patients/{pid}/messages', {'text': 'Сообщение после выхода врача'}, 201)
    assert len(patient_client.get(f'/api/patients/{pid}/messages').json()) == 3


@pytest.mark.parametrize('payload', [
    {'sub': '1', 'jti': 'nonexistent'},
    {'sub': 'invalid', 'jti': 'nonexistent', 'iat': 1, 'exp': 2},
])
def test_invalid_jwt(client, payload):
    token = jwt.encode({**payload, 'iss': 'clinical-compass', 'aud': 'clinical-compass-web'}, settings.jwt_secret_key, algorithm='HS256')
    client.cookies.set('cc_session', token)
    assert client.get('/api/auth/me').status_code == 401


def test_csrf_origin_and_jwt_tampering(patient_client):
    csrf = patient_client.headers.pop('X-CSRF-Token')
    post(patient_client, '/api/urgent-help', {'event_key': 'test-event-123'}, 403)
    patient_client.headers['X-CSRF-Token'] = csrf
    response = patient_client.post('/api/urgent-help', json={'event_key': 'test-event-123'}, headers={'Origin': 'https://evil.example'})
    assert response.status_code == 403
    token = patient_client.cookies.get('cc_session')
    patient_client.cookies.clear()
    parts = token.split('.')
    parts[1] = parts[1][::-1]
    patient_client.cookies.set('cc_session', '.'.join(parts))
    assert patient_client.get('/api/auth/me').status_code == 401


def test_expired_and_wrong_algorithm(patient_client, db_factory):
    cookie = patient_client.cookies.get('cc_session')
    payload = jwt.decode(cookie, settings.jwt_secret_key, algorithms=['HS256'], audience='clinical-compass-web')
    for algorithm in ['HS384', 'HS256']:
        claims = {**payload, 'exp': datetime.now(timezone.utc) - timedelta(seconds=1)} if algorithm == 'HS256' else payload
        patient_client.cookies.clear()
        patient_client.cookies.set('cc_session', jwt.encode(claims, settings.jwt_secret_key, algorithm=algorithm))
        assert patient_client.get('/api/auth/me').status_code == 401


def test_unlinked_invitation_flow(client, doctor_client, actors, db_factory, mailbox):
    data = {'email': 'invitee@example.com', 'full_name': 'Приглашённый', 'password': PASSWORD}
    registered = post(client, '/api/auth/register', data, 201)
    invitation = post(doctor_client, '/api/invitations', {'email': data['email']}, 201)
    invitation['token'] = mailbox[-1]['token']
    post(client, '/api/auth/login', {'email': data['email'], 'password': PASSWORD})
    client.headers['X-CSRF-Token'] = client.cookies.get('cc_csrf')
    post(client, '/api/invitations/accept', {'token': 'x' * 40}, 400)
    linked = post(client, '/api/invitations/accept', {'token': invitation['token']})
    assert linked['doctor_id'] == actors['doctor'].id
    post(client, '/api/invitations/accept', {'token': invitation['token']})
    assert registered['id'] in [p['id'] for p in doctor_client.get('/api/patients').json()]
    with db_factory() as db:
        stored = db.scalar(select(Invitation))
        assert stored.token_hash == digest(invitation['token'])
        assert stored.token_hash != invitation['token']


def test_invite_wrong_email_expired_and_no_silent_reassignment(doctor_client, patient_client, actors, db_factory, mailbox):
    other = post(doctor_client, '/api/invitations', {'email': 'other@example.com'}, 201)
    other['token'] = mailbox[-1]['token']
    post(patient_client, '/api/invitations/accept', {'token': other['token']}, 400)
    own = post(doctor_client, '/api/invitations', {'email': actors['patient'].email}, 201)
    own['token'] = mailbox[-1]['token']
    post(patient_client, '/api/invitations/accept', {'token': own['token']}, 409)
    with db_factory() as db:
        row = db.scalar(select(Invitation).where(Invitation.token_hash == digest(own['token'])))
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    post(patient_client, '/api/invitations/accept', {'token': own['token']}, 400)


@pytest.mark.parametrize('suffix', ['', '/results', '/series', '/plans', '/adherence', '/adherence/summary', '/adverse-events', '/messages', '/alerts', '/recommendations', '/audit'])
def test_foreign_patient_access(doctor_client, patient_client, actors, suffix):
    url = f"/api/patients/{actors['otherpatient'].id}{suffix}"
    assert doctor_client.get(url).status_code == 404
    assert patient_client.get(url).status_code in {403, 404}


def test_role_and_anonymous_guards(client, patient_client, doctor_client, actors):
    assert client.get('/api/patients').status_code == 401
    assert client.get(f"/api/patients/{actors['patient'].id}/results").status_code == 401
    assert client.post('/api/questionnaires/demo/submit', json={'answers': [0]*5}).status_code == 401
    assert patient_client.get('/api/patients').status_code == 403
    post(patient_client, '/api/invitations', {'email': 'x@example.com'}, 403)
    post(patient_client, '/api/recommendations/preview', {'answers': [0]*5}, 403)
    post(doctor_client, '/api/questionnaires/demo/submit', {'answers': [0]*5}, 403)
    post(doctor_client, '/api/urgent-help', {'event_key': 'event-12345'}, 403)
    assert patient_client.get('/api/drugs').status_code == 403


def test_results_history_and_recommendations(patient_client, doctor_client, actors, db_factory):
    pid = actors['patient'].id
    for answers in ([0, 1, 3, 1, 2], [2, 1, 0, 0, 0]):
        result = post(patient_client, '/api/questionnaires/demo/submit', {'answers': answers})
        assert result['score'] == sum(answers)
        assert result['scale_version'] == '1' and result['patient_id'] == pid
    rows = doctor_client.get(f'/api/patients/{pid}/results').json()
    assert len(rows) == 2
    assert rows == patient_client.get(f'/api/patients/{pid}/results').json()
    assert doctor_client.get(f'/api/patients/{pid}/results?scale=gad-7').json() == []
    assert doctor_client.get(f'/api/patients/{pid}/results?start=2099-01-01T00:00:00Z').json() == []
    assert doctor_client.get(f'/api/patients/{pid}/results?version=999').json() == []
    assert doctor_client.get(f'/api/patients/{pid}/results?start=2099-01-01&end=2000-01-01').status_code == 422
    series = doctor_client.get(f'/api/patients/{pid}/series').json()
    assert len(series) == 1 and series[0]['version'] == '1'
    assert [p['score'] for p in series[0]['points']] == [7, 3]
    recs = doctor_client.get(f'/api/patients/{pid}/recommendations').json()
    assert {r['code'] for r in recs} == {'sleep_discussion', 'concentration_discussion'}
    assert all(r['rule_version'] == 'demo_rule_v1' and r['explanation'] for r in recs)
    for index, rec in enumerate(recs):
        decision = ['accepted', 'rejected'][index]
        reviewed = post(doctor_client, f"/api/patients/{pid}/recommendations/{rec['id']}/review", {'status': decision, 'comment': 'Синтетическое решение'})
        assert reviewed['status'] == decision
        post(doctor_client, f"/api/patients/{pid}/recommendations/{rec['id']}/review", {'status': decision, 'comment': 'Повтор'}, 409)
    assert patient_client.get(f'/api/patients/{pid}/recommendations').status_code == 403
    assert doctor_client.get(f'/api/patients/{pid}/plans').json() == []
    with db_factory() as db:
        assert db.scalar(select(QuestionnaireResult)).answers == [0, 1, 3, 1, 2]


@pytest.mark.parametrize('answers', [[0]*4, [0]*6, [0, 0, -1, 0, 0], [True]*5, [1.5]*5])
def test_strict_scoring_validation(patient_client, answers):
    post(patient_client, '/api/questionnaires/demo/submit', {'answers': answers}, 422)


def test_inactive_clinical_scales(patient_client):
    scales = patient_client.get('/api/scales').json()
    assert {s['code'] for s in scales if not s['active']} == {'phq-9', 'gad-7'}
    for code in ['phq-9', 'gad-7', 'unknown']:
        post(patient_client, f'/api/scales/{code}/1/submit', {'answers': [0]*5}, 409)


def test_alert_idempotency_delivery_and_ack(patient_client, doctor_client, actors):
    alert = post(patient_client, '/api/urgent-help', {'event_key': 'explicit-request-1'}, 201)['alert']
    duplicate = post(patient_client, '/api/urgent-help', {'event_key': 'explicit-request-1'}, 201)['alert']
    assert alert['id'] == duplicate['id'] and alert['severity'] == 'critical'
    rows = doctor_client.get('/api/alerts?active_only=true').json()
    assert len(rows) == 1 and rows[0]['patient_id'] == actors['patient'].id
    attempts = doctor_client.get(f"/api/alerts/{alert['id']}/deliveries").json()
    assert len(attempts) == 1 and attempts[0]['status'] == 'available_in_inbox'
    with signed_in(actors['otherdoctor']) as other:
        assert other.get('/api/alerts').json() == []
        post(other, f"/api/alerts/{alert['id']}/acknowledge", status=404)
        assert other.get(f"/api/alerts/{alert['id']}/deliveries").status_code == 404
    post(patient_client, f"/api/alerts/{alert['id']}/acknowledge", status=403)
    assert post(doctor_client, f"/api/alerts/{alert['id']}/acknowledge")['status'] == 'acknowledged'
    post(doctor_client, f"/api/alerts/{alert['id']}/acknowledge")
    assert doctor_client.get('/api/alerts?active_only=true').json() == []
    assert len(doctor_client.get('/api/alerts').json()) == 1


def test_plan_confirmation_versions_and_audit(patient_client, doctor_client, actors):
    pid = actors['patient'].id
    plan = create_plan(doctor_client, pid)
    assert plan['status'] == 'draft'
    assert patient_client.get(f'/api/patients/{pid}/plans').json() == []
    post(patient_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm", status=403)
    post(doctor_client, f"/api/patients/{actors['otherpatient'].id}/plans/{plan['id']}/confirm", status=404)
    confirmed = post(doctor_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm")
    assert confirmed['confirmed_by'] == actors['doctor'].id
    newer = create_plan(doctor_client, pid, instructions='Новая версия наблюдения')
    post(doctor_client, f"/api/patients/{pid}/plans/{newer['id']}/confirm")
    rows = patient_client.get(f'/api/patients/{pid}/plans').json()
    assert [p['status'] for p in rows] == ['active', 'superseded']
    assert [p['version'] for p in rows] == [2, 1]
    post(doctor_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm", status=409)
    actions = [a['action'] for a in doctor_client.get(f'/api/patients/{pid}/audit').json()]
    assert actions.count('confirmed') == 2 and 'superseded' in actions


def test_unverified_drug_blocked_and_verification(doctor_client, patient_client, actors):
    pid = actors['patient'].id
    aviandr = doctor_client.get('/api/drugs').json()[0]
    assert aviandr['name'] == 'Авиандр' and aviandr['status'] == 'pending_validation'
    create = {'title': 'Черновик', 'instructions': 'Учебный', 'prescriptions': [{'drug_id': aviandr['id'], 'regimen': 'Синтетическая инструкция'}]}
    post(doctor_client, f'/api/patients/{pid}/plans', create, 409)
    post(doctor_client, f"/api/drugs/{aviandr['id']}/verify", {'registered_rf': True, 'comment': 'Нет проверенных сведений'}, 409)
    # Synthetic metadata only: this fixture does NOT assert a real registration or regimen.
    data = {'name': 'СИНТЕТИЧЕСКАЯ ЗАПИСЬ — НЕ ПРЕПАРАТ', 'indications': 'Тест', 'contraindications': 'Тест',
            'dosing': 'Тест, не схема лечения', 'source_url': 'https://grls.rosminzdrav.ru/synthetic-test-record',
            'registration_number': 'SYNTHETIC-TEST'}
    post(doctor_client, '/api/drugs', {**data, 'source_url': 'https://evil.example/record'}, 422)
    drug = post(doctor_client, '/api/drugs', data, 201)
    post(patient_client, f"/api/drugs/{drug['id']}/verify", {'registered_rf': True, 'comment': 'Тест'}, 403)
    post(doctor_client, f"/api/drugs/{drug['id']}/verify", {'registered_rf': True, 'comment': 'Синтетическое подтверждение для теста'})
    plan = create_plan(doctor_client, pid, prescriptions=[{'drug_id': drug['id'], 'regimen': 'Тест, не для использования'}])
    assert plan['prescriptions'][0]['drug']['registration_number'] == 'SYNTHETIC-TEST'
    post(doctor_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm")
    assert patient_client.get(f'/api/patients/{pid}/plans').json()[0]['prescriptions'][0]['drug']['source_url'] == data['source_url']


def test_adherence_and_adverse_events(patient_client, doctor_client, actors):
    pid = actors['patient'].id
    plan = create_plan(doctor_client, pid)
    report = {'plan_id': plan['id'], 'report_date': report_date().isoformat(), 'status': 'missed', 'note': 'Синтетический пропуск'}
    post(patient_client, f'/api/patients/{pid}/adherence', report, 404)
    post(doctor_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm")
    post(patient_client, f'/api/patients/{pid}/adherence', report, 201)
    post(patient_client, f'/api/patients/{pid}/adherence', report, 409)
    post(patient_client, f'/api/patients/{pid}/adherence', {**report, 'report_date': '2999-01-01'}, 422)
    assert doctor_client.get(f'/api/patients/{pid}/adherence/summary').json()['missed'] == 1
    event = post(patient_client, f'/api/patients/{pid}/adverse-events', {'plan_id': plan['id'], 'onset_date': report_date().isoformat(), 'description': 'Синтетическое явление'}, 201)
    alerts = doctor_client.get('/api/alerts').json()
    assert alerts[0]['severity'] == 'info' and alerts[0]['kind'] == 'adverse_event_reported'
    reviewed = post(doctor_client, f"/api/patients/{pid}/adverse-events/{event['id']}/review", {'comment': 'Учебное рассмотрение'})
    assert reviewed['status'] == 'reviewed'
    assert patient_client.get(f'/api/patients/{pid}/adverse-events').json()[0]['comment'] == 'Учебное рассмотрение'


def test_chat_and_foreign_mutations(patient_client, doctor_client, actors):
    pid, foreign = actors['patient'].id, actors['otherpatient'].id
    post(patient_client, f'/api/patients/{pid}/messages', {'text': 'Учебный вопрос'}, 201)
    post(doctor_client, f'/api/patients/{pid}/messages', {'text': 'Учебный ответ'}, 201)
    rows = patient_client.get(f'/api/patients/{pid}/messages').json()
    assert [r['text'] for r in rows] == ['Учебный вопрос', 'Учебный ответ']
    assert rows == doctor_client.get(f'/api/patients/{pid}/messages').json()
    post(patient_client, f'/api/patients/{pid}/messages', {'text': '  '}, 422)
    post(patient_client, f'/api/patients/{foreign}/messages', {'text': 'Чужая запись'}, 404)
    post(doctor_client, f'/api/patients/{foreign}/messages', {'text': 'Чужая запись'}, 404)
    post(patient_client, f'/api/patients/{foreign}/adverse-events', {'onset_date': report_date().isoformat(), 'description': 'Чужая запись'}, 404)
    post(patient_client, f'/api/patients/{foreign}/adherence', {'plan_id': 1, 'report_date': report_date().isoformat(), 'status': 'missed'}, 404)


def test_unreviewed_automatic_rules_never_fire(patient_client, doctor_client, actors, db_factory):
    from app.backend.models.clinical import ClinicalAlertRule
    with db_factory() as db:
        # Synthetic configuration verifies the technical gate, not a clinical criterion.
        rule = ClinicalAlertRule(code='synthetic', version='1', scale_code='demo', scale_version='1',
                                 evaluator='score_at_least', parameters={'threshold': 0},
                                 source='SYNTHETIC TEST ONLY', severity='warning', message='Synthetic event', active=True)
        db.add(rule)
        db.commit()
    post(patient_client, '/api/questionnaires/demo/submit', {'answers': [0]*5})
    assert doctor_client.get('/api/alerts').json() == []
    with db_factory() as db:
        rule = db.scalar(select(ClinicalAlertRule))
        rule.review_status, rule.reviewed_by, rule.reviewed_at = 'expert_reviewed', actors['doctor'].id, datetime.now(timezone.utc)
        db.commit()
    post(patient_client, '/api/questionnaires/demo/submit', {'answers': [0]*5})
    assert len(doctor_client.get('/api/alerts').json()) == 1


def test_extensible_scale_versions_remain_separate(patient_client, doctor_client, actors, db_factory, monkeypatch):
    from app.backend.models.clinical import Scale
    from app.backend.services.scales import SCORERS, Scored
    monkeypatch.setitem(SCORERS, 'synthetic_two_questions', lambda answers: Scored(sum(answers), 2, 'Synthetic test only'))
    with db_factory() as db:
        db.add(Scale(code='synthetic', version='2', title='Synthetic test only',
                     questions=[{'id': i, 'text': 'Synthetic', 'options': ['A', 'B']} for i in [1, 2]],
                     scoring_key='synthetic_two_questions', interpretation={}, validation_source='TEST ONLY',
                     license='TEST ONLY', review_status='validated', active=True))
        db.commit()
    post(patient_client, '/api/questionnaires/demo/submit', {'answers': [0]*5})
    post(patient_client, '/api/scales/synthetic/2/submit', {'answers': [1, 1]})
    post(patient_client, '/api/scales/synthetic/2/submit', {'answers': [1, 2]}, 422)
    series = doctor_client.get(f"/api/patients/{actors['patient'].id}/series").json()
    assert {(s['scale'], s['version']) for s in series} == {('demo', '1'), ('synthetic', '2')}


def test_foreign_nested_records_are_not_accessible(patient_client, doctor_client, actors):
    foreign = actors['otherpatient'].id
    with signed_in(actors['otherdoctor']) as other:
        plan = create_plan(other, foreign)
        post(other, f"/api/patients/{foreign}/plans/{plan['id']}/confirm")
    pid = actors['patient'].id
    post(patient_client, f'/api/patients/{pid}/adherence', {'plan_id': plan['id'], 'report_date': report_date().isoformat(), 'status': 'missed'}, 404)
    post(patient_client, f'/api/patients/{pid}/adverse-events', {'plan_id': plan['id'], 'onset_date': report_date().isoformat(), 'description': 'Test only'}, 404)
    post(doctor_client, f"/api/patients/{pid}/plans/{plan['id']}/confirm", status=404)


def test_doctor_cli_is_controlled(client, db_factory, monkeypatch, capsys):
    from app.backend import cli
    monkeypatch.setattr(cli, 'SessionLocal', db_factory)
    monkeypatch.setattr(cli, 'getpass', lambda prompt: PASSWORD)
    monkeypatch.setattr('sys.argv', ['cli', 'create-doctor', '--email', 'cli-doctor@example.com', '--name', 'Synthetic doctor'])
    cli.main()
    assert 'Врач создан' in capsys.readouterr().out
    with db_factory() as db:
        user = db.scalar(select(User).where(User.email == 'cli-doctor@example.com'))
        assert user.role == 'doctor' and user.password_hash.startswith('$argon2id$')
    with pytest.raises(SystemExit):
        cli.main()
