"""Reproducible integration scenario against the live API and actual PostgreSQL.

Run from the repository root after migrations and API startup:
    .venv/bin/python -m scripts.smoke_api --base-url http://127.0.0.1:8010

Uses the same .env as the server. Creates unique synthetic accounts and preserves
all medical history, messages and uploads. It does not execute AI jobs or claim a
successful model inference: inspect their real states in the printed result.
"""
import argparse
from contextlib import ExitStack
from datetime import timedelta
from io import BytesIO
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from websockets.sync.client import connect

from app.backend.auth import hash_password
from app.backend.clinical import ensure_standard_templates
from app.backend.config import settings
from database.connection import SessionLocal
from database.models import User, utcnow


class ScenarioFailure(RuntimeError):
    pass


def check(condition, message):
    if not condition:
        raise ScenarioFailure(message)


def passed(message):
    print(f'OK  {message}', flush=True)


class API:
    def __init__(self, client):
        self.client = client
        self.request('GET', '/api/auth/csrf')

    def request(self, method, path, *, expected=200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        csrf = self.client.cookies.get('cc_csrf')
        if csrf:
            self.client.headers['X-CSRF-Token'] = csrf
        if response.status_code != expected:
            # Responses are synthetic, but avoid printing cookies or passwords.
            detail = response.text[:700]
            raise ScenarioFailure(f'{method} {path}: HTTP {response.status_code}, expected {expected}: {detail}')
        return response

    def login(self, email, password):
        return self.request('POST', '/api/auth/login', json={'email': email, 'password': password}).json()

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def post(self, path, **kwargs):
        return self.request('POST', path, **kwargs)

    def put(self, path, **kwargs):
        return self.request('PUT', path, **kwargs)


def synthetic_pdf():
    """Small valid text PDF; extraction doesn't require OCR or private inputs."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 50 760 Td (SYNTHETIC TEST DOCUMENT. No real patient data.) Tj 0 -20 Td (Purpose: private upload, download and source extraction verification.) Tj ET')
    page.replace_contents(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def websocket_url(base_url, patient_id, api):
    base = urlsplit(base_url)
    return urlunsplit(('wss' if base.scheme == 'https' else 'ws', base.netloc,
                      f'/ws/chat/{patient_id}', urlencode({'csrf': api.client.cookies.get('cc_csrf')}), ''))


def websocket_headers(api):
    return {'Cookie': '; '.join(f'{name}={api.client.cookies.get(name)}' for name in ['cc_session', 'cc_csrf'])}


def run(base_url, origin):
    run_id = uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    emails = {role: f'cc-smoke-{role}-{run_id}@example.com' for role in ['doctor', 'foreign', 'patient']}
    with ExitStack() as stack:
        doctor = API(stack.enter_context(httpx.Client(base_url=base_url, timeout=30)))
        patient = API(stack.enter_context(httpx.Client(base_url=base_url, timeout=30)))
        foreign = API(stack.enter_context(httpx.Client(base_url=base_url, timeout=30)))
        health = doctor.get('/api/health').json()
        check(health.get('synthetic_only') is True, 'API health must identify a synthetic environment')
        passed('Live API health')

        # Developer-provisioned doctors are the only user bootstrap done via SQL.
        with SessionLocal() as db:
            for role in ['doctor', 'foreign']:
                db.add(User(email=emails[role], name=f'SMOKE {role} {run_id}', role='doctor',
                            password_hash=hash_password(password), timezone='Europe/Moscow'))
            ensure_standard_templates(db)
            db.commit()
        doctor_user = doctor.login(emails['doctor'], password)
        foreign.login(emails['foreign'], password)
        invitation = doctor.post('/api/auth/invitations', json={'email': emails['patient'], 'expires_hours': 1}).json()
        token = parse_qs(urlsplit(invitation['link']).query)['invite'][0]
        patient_user = patient.post('/api/auth/register', json={'token': token, 'name': f'SMOKE patient {run_id}',
                                     'password': password, 'timezone': 'Europe/Moscow'}).json()
        pid = patient_user['id']
        check(patient.get('/api/auth/me').json()['id'] == pid, 'Patient cookie session missing')
        check(doctor.get(f'/api/patients/{pid}').json()['doctor_id'] == doctor_user['id'], 'Invitation assigned the wrong doctor')
        patient.post('/api/auth/register', expected=400, json={'token': token, 'name': 'SMOKE duplicate', 'password': password})
        csrf = patient.client.headers.pop('X-CSRF-Token')
        try:
            patient.post(f'/api/patients/{pid}/diary', expected=403, json={'mood': 5, 'anxiety': 5, 'sleep': 5, 'energy': 5, 'wellbeing': 5})
        finally:
            patient.client.headers['X-CSRF-Token'] = csrf
        passed('Invitation, one-time registration, cookie sessions and CSRF rejection')

        record_path = f'/api/patients/{pid}/record'
        doctor.put(record_path, json={'data': {'diagnosis': 'СИНТЕТИЧЕСКИЙ депрессивный эпизод', 'diagnosis_code': 'F32.1',
                                              'allergies': 'Нет подтверждённых сведений', 'anamnesis': 'Синтетический интеграционный сценарий'},
                                     'birth_date': '1990-01-01'})
        report = patient.put(record_path, json={'data': {'allergies': 'СИНТЕТИЧЕСКОЕ сообщение пациента'}}).json()
        check(report['reported']['allergies'] != report['confirmed']['allergies'], 'Reported data replaced the confirmed record')
        check(len(report['history']) == 2, 'Record audit history missing')
        foreign.get(record_path, expected=404)
        passed('Verified/reported record separation, audit and foreign-doctor denial')

        custom_schema = {'questions': [
            {'id': 'one', 'label': 'Синтетический одиночный выбор', 'type': 'single', 'options': [{'value': 'yes', 'label': 'Да'}, {'value': 'no', 'label': 'Нет'}]},
            {'id': 'many', 'label': 'Синтетический множественный выбор', 'type': 'multiple', 'options': [{'value': 'a', 'label': 'А'}, {'value': 'b', 'label': 'Б'}]},
            {'id': 'scale', 'label': 'Синтетическая шкала', 'type': 'number', 'min': 0, 'max': 10},
            {'id': 'text', 'label': 'Комментарий', 'type': 'text'},
        ]}
        template = doctor.post('/api/templates', expected=201, json={'name': f'SMOKE custom {run_id}', 'schema': custom_schema}).json()
        custom = doctor.post(f'/api/patients/{pid}/assignments', expected=201,
                             json={'template_id': template['id'], 'due_at': utcnow().isoformat(), 'schedule': {'frequency': 'once'}}).json()
        doctor.put(f'/api/templates/{template["id"]}', json={'name': f'SMOKE changed {run_id}', 'schema': {'questions': [{'id': 'different', 'type': 'text', 'label': 'Другой вопрос'}]}})
        custom_response = patient.post(f'/api/assignments/{custom["id"]}/responses', expected=201,
                                      json={'answers': {'one': 'yes', 'many': ['a', 'b'], 'scale': 7, 'text': 'Синтетический ответ'}}).json()
        check(custom_response['score'] is None, 'Custom questionnaire received a clinical score')
        phq = next(t for t in doctor.get('/api/templates').json() if t['kind'] == 'phq9')
        assignment = doctor.post(f'/api/patients/{pid}/assignments', expected=201,
                                 json={'template_id': phq['id'], 'due_at': utcnow().isoformat(), 'schedule': {'frequency': 'once'}}).json()
        answers = {f'q{i}': 2 for i in range(1, 10)}
        answers['q9'] = 1
        submission = {'answers': answers, 'idempotency_key': f'smoke-{run_id}'}
        scored = patient.post(f'/api/assignments/{assignment["id"]}/responses', expected=201, json=submission).json()
        duplicate = patient.post(f'/api/assignments/{assignment["id"]}/responses', expected=201, json=submission).json()
        check(scored['score'] == 17 and duplicate['id'] == scored['id'], 'PHQ-9 score or submission deduplication failed')
        check(patient.get(f'/api/patients/{pid}').json()['status'] == 'red', 'Immediate PHQ-9 item 9 rule did not run')
        passed('Four custom question types, immutable assignment snapshot, PHQ-9 scoring and immediate critical rule')

        local_slot = utcnow().astimezone(ZoneInfo('Europe/Moscow')).replace(second=0, microsecond=0)
        prescription_values = {'name': f'СИНТЕТИЧЕСКИЙ препарат {run_id}', 'dose': '10', 'unit': 'условных единиц',
                               'times': [local_slot.strftime('%H:%M')], 'start_date': (local_slot.date() - timedelta(days=1)).isoformat(),
                               'comment': 'Только синтетический тест; не клиническое назначение'}
        rx = doctor.post(f'/api/patients/{pid}/prescriptions', expected=201, json=prescription_values).json()
        intake = patient.post(f'/api/prescriptions/{rx["id"]}/intakes', expected=201,
                              json={'scheduled_at': local_slot.isoformat(), 'actual_at': utcnow().isoformat(), 'status': 'taken',
                                    'side_effect': 'СИНТЕТИЧЕСКОЕ сообщение', 'severity': 2}).json()
        check(intake['version'] == 1, 'Intake version missing')
        changed = doctor.put(f'/api/prescriptions/{rx["id"]}', json={**prescription_values, 'dose': '20'}).json()
        check(changed['current_version'] == 2 and [v['data']['dose'] for v in changed['versions']] == ['10', '20'], 'Prescription history was replaced')
        passed('Prescription, actual intake, reported side effect and immutable treatment versions')

        doctor.put(f'/api/patients/{pid}/diary-schedule', json={'times': ['09:00', '20:00']})
        diary = patient.post(f'/api/patients/{pid}/diary', expected=201,
                             json={'mood': 7, 'anxiety': 3, 'sleep': 7, 'energy': 6, 'wellbeing': 7, 'comment': 'СИНТЕТИЧЕСКИЙ дневник'}).json()
        check(diary['mood'] == 7 and patient.get(f'/api/patients/{pid}').json()['status'] == 'red', 'Diary or critical-rule protection failed')
        ai = doctor.get(f'/api/patients/{pid}/ai').json()
        check(any(job['kind'] == 'analysis' for job in ai['jobs']), 'Patient submissions did not queue durable AI analysis')
        alerts = doctor.get(f'/api/patients/{pid}/alerts').json()
        critical = next(a for a in alerts if a['category'] == 'self_harm_screen')
        reviewed = doctor.post(f'/api/alerts/{critical["id"]}/actions', json={'action': 'seen', 'comment': 'СИНТЕТИЧЕСКАЯ проверка интерфейса'}).json()
        check(reviewed['state'] == 'seen' and len(reviewed['actions']) == 1, 'Doctor alert feedback history missing')
        passed('Diary, protected red indicator, durable AI queue and doctor feedback')

        pdf = synthetic_pdf()
        document = patient.post(f'/api/patients/{pid}/documents', expected=201,
                                files={'file': (f'smoke-{run_id}.pdf', pdf, 'application/pdf')}).json()
        doc_path = f'/api/documents/{document["id"]}/download'
        check(patient.get(doc_path).content == pdf and doctor.get(doc_path).content == pdf, 'Document download changed the original')
        foreign.get(doc_path, expected=404)
        attachment = patient.post(f'/api/patients/{pid}/chat/attachments',
                                  files={'file': (f'smoke-chat-{run_id}.pdf', pdf, 'application/pdf')}).json()
        check(doctor.get(f'/api/chat/attachments/{attachment["id"]}').content == pdf, 'Chat attachment download failed')
        foreign.get(f'/api/chat/attachments/{attachment["id"]}', expected=404)
        passed('Private patient PDF and chat attachments, exact download and foreign-doctor denial')

        with connect(websocket_url(base_url, pid, patient), origin=origin,
                     additional_headers=websocket_headers(patient), open_timeout=10) as patient_socket:
            with connect(websocket_url(base_url, pid, doctor), origin=origin,
                         additional_headers=websocket_headers(doctor), open_timeout=10) as doctor_socket:
                patient_socket.send(json.dumps({'text': f'СИНТЕТИЧЕСКОЕ сообщение пациента {run_id}'}))
                for socket in (patient_socket, doctor_socket):
                    message = json.loads(socket.recv(timeout=10))
                    check(message['sender_id'] == pid and run_id in message['text'], 'Patient WebSocket message was not broadcast')
                doctor_socket.send(json.dumps({'text': f'СИНТЕТИЧЕСКИЙ ответ врача {run_id}'}))
                for socket in (patient_socket, doctor_socket):
                    message = json.loads(socket.recv(timeout=10))
                    check(message['sender_id'] == doctor_user['id'], 'Doctor WebSocket message was not broadcast')
        patient.post(f'/api/patients/{pid}/chat', json={'text': 'СИНТЕТИЧЕСКОЕ вложение', 'attachment_id': attachment['id']})
        history = doctor.get(f'/api/patients/{pid}/chat').json()
        check(len(history) == 3 and history[-1]['attachment']['id'] == attachment['id'], 'Chat history was not persisted')
        foreign.get(f'/api/patients/{pid}/chat', expected=404)
        passed('Authenticated two-way WebSocket chat, persistent history and room isolation')

        print(f'PASS run={run_id} patient_id={pid} doctor_id={doctor_user["id"]}', flush=True)
        print(f'Synthetic accounts: {emails["doctor"]}, {emails["patient"]}', flush=True)
        states = {job['status'] for job in ai['jobs']}
        print(f'AI queue states observed: {", ".join(sorted(states))}. Model inference was not executed by this script.', flush=True)
        print('All synthetic history and files were preserved.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Live synthetic API/PostgreSQL/WebSocket integration scenario')
    parser.add_argument('--base-url', default='http://127.0.0.1:8010')
    parser.add_argument('--origin', default=settings.origins[0] if settings.origins else 'http://localhost:5174',
                        help='Allowed WebSocket Origin; must match the server ALLOWED_ORIGINS')
    args = parser.parse_args()
    try:
        run(args.base_url.rstrip('/'), args.origin)
    except (ScenarioFailure, httpx.HTTPError, OSError, TimeoutError) as error:
        raise SystemExit(f'FAIL {error}') from None


if __name__ == '__main__':
    main()
