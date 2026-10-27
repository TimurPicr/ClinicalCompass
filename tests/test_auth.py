from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
from sqlalchemy import select
from app.backend.auth import digest
from database.models import AuthSession, Invitation, Patient, ResetToken, User, utcnow

def test_invitation_registration_single_use(doctor_client,db,doctor):
    response=doctor_client.post('/api/auth/invitations',json={'email':'new@example.com'})
    assert response.status_code==200,response.text
    token=parse_qs(urlsplit(response.json()['link']).query)['invite'][0]
    body={'token':token,'name':'Новый пациент','password':'LongPassword123!','timezone':'Europe/Moscow'}
    result=doctor_client.post('/api/auth/register',json=body)
    assert result.status_code==200,result.text
    user=db.get(User,result.json()['id'])
    assert user.role=='patient'
    assert db.get(Patient,user.id).doctor_id==doctor.id
    doctor_client.headers['X-CSRF-Token']=doctor_client.cookies.get('cc_csrf')
    assert doctor_client.post('/api/auth/register',json=body).status_code==400
    assert doctor_client.post('/api/auth/invitations',json={'email':'bad@example.com'}).status_code==403

def test_expired_invitation(client,db,doctor):
    token='x'*40
    db.add(Invitation(doctor_id=doctor.id,email='expired@example.com',token_hash=digest(token),expires_at=utcnow()-timedelta(seconds=1)))
    db.commit()
    assert client.post('/api/auth/register',json={'token':token,'name':'Пациент','password':'LongPassword123!'}).status_code==400

def test_login_cookie_csrf_and_logout(client,doctor):
    assert client.post('/api/auth/login',json={'email':doctor.email,'password':'wrong'}).status_code==401
    response=client.post('/api/auth/login',json={'email':doctor.email,'password':'TestPassword123!'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers.get_list('set-cookie')[0]
    assert 'password_hash' not in response.json()
    assert client.get('/api/auth/me').json()['id']==doctor.id
    assert client.post('/api/auth/logout').status_code==403 # rotated CSRF
    client.headers['X-CSRF-Token']=client.cookies.get('cc_csrf')
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me').status_code==401

def test_reset_revokes_sessions_once(doctor_client,doctor,db):
    token='t'*40
    db.add(ResetToken(user_id=doctor.id,token_hash=digest(token),expires_at=utcnow()+timedelta(hours=1)))
    db.commit()
    old_ids=list(db.scalars(select(AuthSession.id)))
    response=doctor_client.post('/api/auth/reset',json={'token':token,'password':'NewPassword123!'})
    assert response.status_code==200
    assert all(db.get(AuthSession,i) is None for i in old_ids)
    doctor_client.headers['X-CSRF-Token']=doctor_client.cookies.get('cc_csrf')
    assert doctor_client.post('/api/auth/reset',json={'token':token,'password':'NewPassword123!'}).status_code==400

def test_csrf_origin(doctor_client):
    assert doctor_client.post('/api/auth/logout',headers={'Origin':'https://attacker.example'}).status_code==403

def test_query_tokens_redacted_from_http_and_websocket_logs():
    import logging
    from app.backend.logging_utils import RedactQuery
    for message,args in [('%s - "%s %s HTTP/%s" %d',('client','GET','/api/auth/invitations/inspect?token=secret','1.1',200)),('%s - "WebSocket %s" [accepted]',('client','/ws/chat/2?csrf=secret'))]:
        record=logging.LogRecord('uvicorn.access',logging.INFO,'',1,message,args,None)
        assert RedactQuery().filter(record)
        assert 'secret' not in record.getMessage()


def test_registration_rejects_whitespace_name(doctor_client,db):
    invite=doctor_client.post('/api/auth/invitations',json={'email':'blank-name@example.com'}).json()
    token=parse_qs(urlsplit(invite['link']).query)['invite'][0]
    response=doctor_client.post('/api/auth/register',json={'token':token,'name':'   ','password':'LongPassword123!'})
    assert response.status_code==422
    invitation=db.scalar(select(Invitation).where(Invitation.token_hash==digest(token)))
    assert invitation.used_at is None
