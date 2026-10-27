"""Doctor inbox contract and real HTTP/WebSocket room lifecycle tests."""
from contextlib import contextmanager
from datetime import timedelta
import io

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import event, select
from starlette.websockets import WebSocketDisconnect

from app.backend import chat
from app.backend.auth import digest
from app.backend.main import app
from database.models import AuthSession, ChatAttachment, Message, Patient, User, utcnow
from tests.conftest import sign_in


def add_patient(db, doctor, name, index):
    user = User(email=f'inbox-{index}@synthetic.test', name=name, role='patient', password_hash='unused')
    db.add(user)
    db.flush()
    db.add(Patient(id=user.id, doctor_id=doctor.id))
    db.flush()
    return user


def add_message(db, patient, sender, text, when, attachment_id=None):
    row = Message(patient_id=patient.id, sender_id=sender.id, text=text,
                  created_at=when, attachment_id=attachment_id)
    db.add(row)
    db.flush()
    return row


def connect(client, patient_id):
    return client.websocket_connect(f'/ws/chat/{patient_id}?csrf={client.cookies.get("cc_csrf")}',
                                    headers={'origin': 'http://testserver'})


@pytest.fixture
def live_clients(client, patient, doctor, db, monkeypatch):
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(chat, 'SessionLocal', session)
    sign_in(client, patient.email)
    with TestClient(app) as physician:
        physician.get('/api/auth/csrf')
        physician.headers['X-CSRF-Token'] = physician.cookies.get('cc_csrf')
        sign_in(physician, doctor.email)
        try:
            yield client, physician
        finally:
            chat.rooms.clear()


def test_inbox_is_doctor_only_and_scoped_to_attached_patients(client, db, doctor, patient, other_doctor):
    empty = add_patient(db, doctor, 'Без переписки', 1)
    foreign = add_patient(db, other_doctor, 'Чужой пациент', 2)
    add_message(db, foreign, foreign, 'Чужая конфиденциальная переписка', utcnow())
    db.commit()
    assert client.get('/api/chats').status_code == 401
    sign_in(client, patient.email)
    assert client.get('/api/chats').status_code == 403
    sign_in(client, doctor.email)
    response = client.get('/api/chats')
    assert response.status_code == 200, response.text
    assert response.json() == [
        {'patient_id': patient.id, 'patient_name': patient.name, 'last_message': None},
        {'patient_id': empty.id, 'patient_name': empty.name, 'last_message': None},
    ]
    assert 'Чужая' not in response.text
    assert client.get(f'/api/patients/{foreign.id}/chat').status_code == 404


def test_inbox_sorts_latest_timestamp_then_id_and_empty_rooms_last(doctor_client, db, doctor, patient):
    now = utcnow()
    tied = add_patient(db, doctor, 'Вторая комната', 1)
    empty = add_patient(db, doctor, 'Пустая комната', 2)
    add_message(db, patient, patient, 'Предыдущий разговор', now - timedelta(days=1))
    first_latest = add_message(db, patient, doctor, 'Новый ответ', now)
    tied_latest = add_message(db, tied, tied, 'Совпадающая дата, больший id', now)
    # Imported chronological history can have a higher id but an older timestamp.
    add_message(db, patient, patient, 'Более старая импортированная запись', now - timedelta(days=2))
    db.commit()
    rows = doctor_client.get('/api/chats').json()
    assert [row['patient_id'] for row in rows] == [tied.id, patient.id, empty.id]
    assert [row['last_message']['id'] for row in rows[:2]] == [tied_latest.id, first_latest.id]
    assert rows[-1]['last_message'] is None


def test_inbox_last_message_uses_same_attachment_and_sender_contract_as_history(patient_client, db, doctor, patient, tmp_path, monkeypatch):
    from app.backend.config import settings
    monkeypatch.setattr(settings, 'upload_dir', tmp_path)
    image = io.BytesIO()
    Image.new('RGB', (16, 16), 'white').save(image, format='PNG')
    uploaded = patient_client.post(f'/api/patients/{patient.id}/chat/attachments',
                                   files={'file': ('results.png', image.getvalue(), 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    sent = patient_client.post(f'/api/patients/{patient.id}/chat',
                              json={'text': 'Результаты для обсуждения', 'attachment_id': uploaded.json()['id']})
    assert sent.status_code == 200, sent.text
    sign_in(patient_client, doctor.email)
    latest = patient_client.get('/api/chats').json()[0]['last_message']
    history = patient_client.get(f'/api/patients/{patient.id}/chat').json()
    assert latest == history[-1]
    assert latest['sender_id'] == patient.id and latest['sender_name'] == patient.name
    assert latest['attachment'] == {
        'id': uploaded.json()['id'], 'name': 'results.png', 'mime': 'image/png',
        'size': len(image.getvalue()), 'url': f'/api/chat/attachments/{uploaded.json()["id"]}',
    }
    assert patient_client.get(latest['attachment']['url']).content == image.getvalue()


def test_inbox_loads_many_senders_and_attachments_with_constant_query_count(doctor_client, db, doctor):
    now = utcnow()
    for index in range(30):
        patient = add_patient(db, doctor, f'Пациент {index}', index)
        attachment = ChatAttachment(patient_id=patient.id, uploader_id=patient.id,
                                    name=f'report-{index}.pdf', storage_name=f'{index:032x}.pdf',
                                    mime='application/pdf', size=10)
        db.add(attachment)
        db.flush()
        add_message(db, patient, patient, 'Приложен документ', now, attachment.id)
    db.commit()
    db.expire_all()
    queries = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            queries.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', record)
    try:
        response = doctor_client.get('/api/chats')
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 30
    assert all(row['last_message']['attachment'] for row in response.json())
    assert len(queries) <= 3, f'Inbox performed {len(queries)} SELECTs for 30 rooms'


def test_history_keeps_hundred_message_id_cursor_and_room_isolation(doctor_client, db, doctor, patient, other_doctor):
    now = utcnow()
    foreign = add_patient(db, other_doctor, 'Чужой пациент', 1)
    ids = []
    for index in range(205):
        ids.append(add_message(db, patient, patient, str(index), now + timedelta(seconds=index)).id)
        if index % 50 == 0:
            add_message(db, foreign, foreign, 'Чужой текст', now)
    db.commit()
    path = f'/api/patients/{patient.id}/chat'
    newest = doctor_client.get(path).json()
    middle = doctor_client.get(path, params={'before': newest[0]['id']}).json()
    oldest = doctor_client.get(path, params={'before': middle[0]['id']}).json()
    assert [len(newest), len(middle), len(oldest)] == [100, 100, 5]
    assert [row['id'] for row in oldest + middle + newest] == ids
    assert all(row['patient_id'] == patient.id for row in oldest + middle + newest)


def test_http_and_websocket_messages_broadcast_to_both_recipients_in_both_directions(live_clients, patient):
    patient_client, doctor_client = live_clients
    with connect(patient_client, patient.id) as patient_ws, connect(doctor_client, patient.id) as doctor_ws:
        http_patient = patient_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Пациент через HTTP'}).json()
        assert patient_ws.receive_json() == http_patient
        assert doctor_ws.receive_json() == http_patient
        http_doctor = doctor_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Врач через HTTP'}).json()
        assert patient_ws.receive_json() == http_doctor
        assert doctor_ws.receive_json() == http_doctor
        patient_ws.send_json({'text': 'Пациент через WebSocket'})
        ws_patient = patient_ws.receive_json()
        assert doctor_ws.receive_json() == ws_patient
        doctor_ws.send_json({'text': 'Врач через WebSocket'})
        ws_doctor = doctor_ws.receive_json()
        assert patient_ws.receive_json() == ws_doctor
        assert ws_patient['sender_id'] == patient.id
        assert ws_doctor['sender_id'] == http_doctor['sender_id']
    history = patient_client.get(f'/api/patients/{patient.id}/chat').json()
    assert history == [http_patient, http_doctor, ws_patient, ws_doctor]
    assert patient.id not in chat.rooms


@pytest.mark.parametrize('csrf', ['', 'wrong-token'])
def test_websocket_handshake_requires_session_csrf(live_clients, patient, csrf):
    patient_client, _ = live_clients
    with pytest.raises(WebSocketDisconnect) as closed:
        with patient_client.websocket_connect(f'/ws/chat/{patient.id}?csrf={csrf}',
                                              headers={'origin': 'http://testserver'}):
            pass
    assert closed.value.code == 4403
    assert patient.id not in chat.rooms


def test_patient_cannot_subscribe_to_another_patients_room(live_clients, patient, doctor, db):
    patient_client, _ = live_clients
    other = add_patient(db, doctor, 'Другой пациент того же врача', 1)
    db.commit()
    with pytest.raises(WebSocketDisconnect) as closed:
        with connect(patient_client, other.id):
            pass
    assert closed.value.code == 4404
    assert other.id not in chat.rooms
    assert patient_client.get(f'/api/patients/{other.id}/chat').status_code == 404
    assert patient_client.post(f'/api/patients/{other.id}/chat', json={'text': 'Чужой пациент'}).status_code == 404


@pytest.mark.parametrize('payload', [[], None, 5, 'не объект', {'text': ''}])
def test_bad_websocket_payload_returns_error_without_killing_connection(live_clients, patient, payload):
    patient_client, _ = live_clients
    with connect(patient_client, patient.id) as ws:
        ws.send_json(payload)
        assert 'error' in ws.receive_json()
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        ws.send_json({'text': 'Соединение осталось рабочим'})
        assert ws.receive_json()['text'] == 'Соединение осталось рабочим'
    assert len(patient_client.get(f'/api/patients/{patient.id}/chat').json()) == 1


@pytest.mark.parametrize('direction', ['send', 'receive'])
@pytest.mark.parametrize('revocation', ['expiry', 'logout'])
def test_revoked_session_closes_existing_socket(live_clients, patient, db, direction, revocation):
    patient_client, doctor_client = live_clients
    token = patient_client.cookies.get('cc_session')
    with connect(patient_client, patient.id) as ws:
        if revocation == 'expiry':
            db.get(AuthSession, digest(token)).expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        else:
            assert patient_client.post('/api/auth/logout').status_code == 200
        if direction == 'send':
            ws.send_json({'type': 'ping'})
        else:
            assert doctor_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'После истечения сессии'}).status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4401
    assert patient_client.get(f'/api/patients/{patient.id}/chat').status_code == 401
    assert patient.id not in chat.rooms


@pytest.mark.parametrize('payload,code', [(b'unsupported binary frame', 1003), ('x' * 15001, 1009)])
def test_unsupported_or_oversized_frame_closes_cleanly_without_persisting(live_clients, patient, db, payload, code):
    patient_client, _ = live_clients
    with connect(patient_client, patient.id) as ws:
        if isinstance(payload, bytes):
            ws.send_bytes(payload)
        else:
            ws.send_text(payload)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == code
    assert not db.scalars(select(Message)).all()
    assert patient.id not in chat.rooms


@pytest.mark.parametrize('direction', ['send', 'receive'])
def test_reassigned_patient_revokes_previous_doctor_socket(live_clients, patient, other_doctor, db, direction):
    patient_client, doctor_client = live_clients
    with connect(doctor_client, patient.id) as ws:
        db.get(Patient, patient.id).doctor_id = other_doctor.id
        db.commit()
        if direction == 'send':
            ws.send_json({'type': 'ping'})
        else:
            assert patient_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Личное сообщение новому врачу'}).status_code == 200
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4404
    assert doctor_client.get('/api/chats').json() == []
    assert doctor_client.get(f'/api/patients/{patient.id}/chat').status_code == 404
    assert patient.id not in chat.rooms


def test_http_message_requires_current_session_csrf_even_if_cookie_matches_header(patient_client, patient, db):
    token = patient_client.cookies.get('cc_csrf')
    patient_client.headers['X-CSRF-Token'] = 'old-token'
    assert patient_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Устаревший заголовок'}).status_code == 403
    patient_client.cookies.set('cc_csrf', 'forged-token', domain='testserver.local', path='/')
    patient_client.headers['X-CSRF-Token'] = 'forged-token'
    assert patient_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Подменённая cookie'}).status_code == 403
    assert not db.scalars(select(Message)).all()
    patient_client.cookies.set('cc_csrf', token, domain='testserver.local', path='/')
    patient_client.headers['X-CSRF-Token'] = token
    assert patient_client.post(f'/api/patients/{patient.id}/chat', json={'text': 'Действительный токен'}).status_code == 200


@pytest.mark.asyncio
async def test_failed_receiver_does_not_block_healthy_recipient_or_leak_room(db, patient, doctor, monkeypatch):
    class Socket:
        cookies = {'cc_session': 'token'}
        def __init__(self, fail=False):
            self.fail, self.received = fail, []
        async def send_json(self, payload):
            if self.fail:
                raise RuntimeError('disconnected')
            self.received.append(payload)
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(chat, 'SessionLocal', session)
    monkeypatch.setattr(chat, 'user_from_token', lambda db, token: doctor)
    failed, healthy = Socket(True), Socket()
    chat.rooms[patient.id].update([failed, healthy])
    try:
        await chat.broadcast(patient.id, {'text': 'Сохранённое сообщение'})
        assert healthy.received == [{'text': 'Сохранённое сообщение'}]
        assert chat.rooms[patient.id] == {healthy}
        healthy.fail = True
        await chat.broadcast(patient.id, {'text': 'Следующее сообщение'})
        assert patient.id not in chat.rooms
    finally:
        chat.rooms.clear()
