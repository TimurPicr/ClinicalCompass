import io
from contextlib import contextmanager
from datetime import timedelta
from PIL import Image
import pytest
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select
from tests.conftest import sign_in
from database.models import Assignment, Patient, PushSubscription, QuestionnaireTemplate, Reminder, utcnow

def test_chat_persistence_attachment_and_access(patient_client,patient,doctor,other_doctor,db,tmp_path,monkeypatch):
    from app.backend.config import settings
    monkeypatch.setattr(settings,'upload_dir',tmp_path)
    text=patient_client.post(f'/api/patients/{patient.id}/chat',json={'text':'Сообщение врачу'})
    assert text.status_code==200,text.text
    assert text.json()['sender_id']==patient.id
    assert len(patient_client.get(f'/api/patients/{patient.id}/chat').json())==1
    image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
    file=patient_client.post(f'/api/patients/{patient.id}/chat/attachments',files={'file':('photo.png',image.getvalue(),'image/png')})
    assert file.status_code==200,file.text
    file_id=file.json()['id']
    sent=patient_client.post(f'/api/patients/{patient.id}/chat',json={'attachment_id':file_id})
    assert sent.json()['attachment']['name']=='photo.png'
    assert patient_client.post(f'/api/patients/{patient.id}/chat',json={'attachment_id':file_id}).status_code==409
    assert patient_client.get(f'/api/chat/attachments/{file_id}').content==image.getvalue()
    sign_in(patient_client,doctor.email)
    assert len(patient_client.get(f'/api/patients/{patient.id}/chat').json())==2
    sign_in(patient_client,other_doctor.email)
    assert patient_client.get(f'/api/patients/{patient.id}/chat').status_code==404
    assert patient_client.get(f'/api/chat/attachments/{file_id}').status_code==404
    assert patient_client.post(f'/api/patients/{patient.id}/chat',json={'text':'bad'}).status_code==404

def test_websocket_authenticated_room_and_origin(patient_client,patient,other_doctor,db,monkeypatch):
    from app.backend import chat
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(chat,'SessionLocal',session)
    csrf=patient_client.cookies.get('cc_csrf')
    with patient_client.websocket_connect(f'/ws/chat/{patient.id}?csrf={csrf}',headers={'origin':'http://testserver'}) as ws:
        ws.send_json({'text':'Настоящий WebSocket'})
        result=ws.receive_json()
        assert result['text']=='Настоящий WebSocket'
        assert result['sender_id']==patient.id
        ws.send_json({'text':''})
        assert 'error' in ws.receive_json()
    assert len(patient_client.get(f'/api/patients/{patient.id}/chat').json())==1
    with pytest.raises(WebSocketDisconnect) as blocked:
        with patient_client.websocket_connect(f'/ws/chat/{patient.id}?csrf={csrf}',headers={'origin':'https://attacker.example'}):
            pass
    assert blocked.value.code==4403
    sign_in(patient_client,other_doctor.email)
    csrf=patient_client.cookies.get('cc_csrf')
    with pytest.raises(WebSocketDisconnect) as blocked:
        with patient_client.websocket_connect(f'/ws/chat/{patient.id}?csrf={csrf}',headers={'origin':'http://testserver'}):
            pass
    assert blocked.value.code==4404

def test_webpush_generic_payload_idempotent_and_private_endpoint(patient_client,patient,db,monkeypatch):
    from app.backend import notifications
    from app.backend.config import settings
    monkeypatch.setattr(settings,'vapid_public_key','public')
    monkeypatch.setattr(settings,'vapid_private_key','private')
    rejected=patient_client.post('/api/notifications/subscribe',json={'endpoint':'https://127.0.0.1/internal','keys':{'auth':'a'*24,'p256dh':'b'*87}})
    assert rejected.status_code==422
    subscribed=patient_client.post('/api/notifications/subscribe',json={'endpoint':'https://fcm.googleapis.com/fcm/send/test','keys':{'auth':'a'*24,'p256dh':'b'*87}})
    assert subscribed.status_code==200
    now=utcnow().replace(second=0,microsecond=0)
    user=patient;user.timezone='UTC'
    profile=db.get(Patient,patient.id);profile.diary_times=[now.strftime('%H:%M')]
    db.commit()
    calls=[]
    monkeypatch.setattr(notifications,'webpush',lambda **kwargs:calls.append(kwargs))
    assert notifications.send_due_reminders(db,now)==1
    assert notifications.send_due_reminders(db,now)==0
    assert len(calls)==1
    assert 'diagnosis' not in calls[0]['data'] and 'препарат' not in calls[0]['data']
    assert db.scalar(select(Reminder)).status=='sent'
    assert patient_client.request('DELETE','/api/notifications/subscribe',json={'endpoint':'https://fcm.googleapis.com/fcm/send/test'}).status_code==200
    assert not db.scalars(select(PushSubscription)).all()


def test_websocket_logout_revokes_receiver(patient_client,patient,doctor,db,monkeypatch):
    from app.backend import chat
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(chat,'SessionLocal',session)
    csrf=patient_client.cookies.get('cc_csrf')
    with patient_client.websocket_connect(f'/ws/chat/{patient.id}?csrf={csrf}',headers={'origin':'http://testserver'}) as ws:
        assert patient_client.post('/api/auth/logout').status_code==200
        patient_client.get('/api/auth/csrf')
        patient_client.headers['X-CSRF-Token']=patient_client.cookies.get('cc_csrf')
        sign_in(patient_client,doctor.email)
        sent=patient_client.post(f'/api/patients/{patient.id}/chat',json={'text':'Сообщение после отзыва сессии'})
        assert sent.status_code==200
        with pytest.raises(WebSocketDisconnect) as disconnected:
            ws.receive_json()
        assert disconnected.value.code==4401


def test_overdue_recurring_questionnaire_keeps_reminding(patient,db):
    from app.backend.notifications import reminder_slots
    now=utcnow().replace(second=0,microsecond=0)
    patient.timezone='UTC'
    profile=db.get(Patient,patient.id);profile.diary_times=[]
    template=QuestionnaireTemplate(name='Синтетический',kind='custom',schema={'questions':[]})
    db.add(template);db.flush()
    assignment=Assignment(patient_id=patient.id,template_id=template.id,snapshot={},due_at=now-timedelta(days=1),schedule={'frequency':'daily','times':[now.strftime('%H:%M')]})
    db.add(assignment);db.commit()
    keys=list(reminder_slots(db,profile,now))
    assert keys==[f'assignment:{assignment.id}:{now.isoformat()}']
    assignment.schedule={'frequency':'weekly','times':[now.strftime('%H:%M')]}
    db.commit()
    assert list(reminder_slots(db,profile,now))==[]
    assignment.due_at=now-timedelta(days=7);db.commit()
    assert list(reminder_slots(db,profile,now))==keys
    assert assignment.due_at<now # a reminder never advances completion/deadline
