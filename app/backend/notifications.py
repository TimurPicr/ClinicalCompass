"""Generic Web Push reminders; no diagnoses or medicine names leave this host."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from pywebpush import webpush, WebPushException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.backend.auth import current_user
from app.backend.config import settings
from database.connection import get_db
from database.models import Assignment, Intake, Patient, Prescription, PrescriptionVersion, PushSubscription, Reminder, User, utcnow

router=APIRouter(prefix='/api/notifications',tags=['Напоминания'])
PUSH_HOSTS=('fcm.googleapis.com','push.services.mozilla.com','web.push.apple.com','notify.windows.com')

class SubscribeInput(BaseModel):
    endpoint: str = Field(max_length=3000)
    keys: dict[str,str]
    expirationTime: float | None = None
    @field_validator('endpoint')
    @classmethod
    def endpoint_allowed(cls,value):
        parsed=urlsplit(value)
        host=parsed.hostname or ''
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443) or not any(host==h or host.endswith('.'+h) for h in PUSH_HOSTS):
            raise ValueError('Неизвестный HTTPS-сервис Web Push')
        return value
    @field_validator('keys')
    @classmethod
    def valid_keys(cls,value):
        if set(value) != {'p256dh','auth'} or any(not 16 <= len(v) <= 180 for v in value.values()):
            raise ValueError('Некорректные ключи подписки')
        return value

@router.get('/public-key')
def public_key(user=Depends(current_user)):
    return {'public_key':settings.vapid_public_key,'enabled':bool(settings.vapid_public_key and settings.vapid_private_key)}

@router.get('/status')
def status(user=Depends(current_user),db=Depends(get_db)):
    return {'configured':bool(settings.vapid_public_key and settings.vapid_private_key),
            'subscriptions':len(db.scalars(select(PushSubscription).where(PushSubscription.user_id==user.id)).all()),
            'server_required':True}

@router.post('/subscribe')
def subscribe(data:SubscribeInput,user=Depends(current_user),db=Depends(get_db)):
    if user.role!='patient':
        raise HTTPException(403,'Напоминания предназначены пациентам')
    if not settings.vapid_public_key or not settings.vapid_private_key:
        raise HTTPException(503,'Сначала настройте VAPID-ключи на сервере')
    row=db.scalar(select(PushSubscription).where(PushSubscription.endpoint==data.endpoint))
    if row and row.user_id!=user.id:
        raise HTTPException(409,'Подписка уже связана с другим пользователем')
    if row:
        row.keys=data.keys
    else:
        db.add(PushSubscription(user_id=user.id,endpoint=data.endpoint,keys=data.keys))
    db.commit()
    return {'ok':True}

@router.delete('/subscribe')
def unsubscribe(data:dict,user=Depends(current_user),db=Depends(get_db)):
    row=db.scalar(select(PushSubscription).where(PushSubscription.endpoint==data.get('endpoint'),PushSubscription.user_id==user.id))
    if row:
        db.delete(row)
        db.commit()
    return {'ok':True}

def reminder_slots(db,patient,now):
    """Yield only the current 15-minute window; do not replay stale reminders."""
    user=db.get(User,patient.id)
    local=now.astimezone(ZoneInfo(user.timezone))
    day=local.date()
    def slot(value):
        try:
            hour,minute=map(int,value.split(':'))
            planned=datetime(day.year,day.month,day.day,hour,minute,tzinfo=local.tzinfo).astimezone(timezone.utc)
            return planned if timedelta(0)<=now-planned<timedelta(minutes=15) else None
        except (ValueError,TypeError):
            return None
    for time in patient.diary_times or []:
        planned=slot(time)
        if planned:
            yield f'diary:{patient.id}:{planned.isoformat()}'
    for prescription in db.scalars(select(Prescription).where(Prescription.patient_id==patient.id,Prescription.active.is_(True))):
        version=db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id==prescription.id,PrescriptionVersion.version==prescription.current_version))
        if not version:
            continue
        data=version.data
        if data.get('start_date','0000')>day.isoformat() or (data.get('end_date') and data['end_date']<day.isoformat()):
            continue
        for time in data.get('times',[]):
            planned=slot(time)
            if planned and not db.scalar(select(Intake.id).where(Intake.prescription_id==prescription.id,Intake.scheduled_at==planned)):
                yield f'intake:{prescription.id}:{planned.isoformat()}'
    for assignment in db.scalars(select(Assignment).where(Assignment.patient_id==patient.id,Assignment.active.is_(True))):
        due=assignment.due_at.replace(tzinfo=timezone.utc) if assignment.due_at.tzinfo is None else assignment.due_at
        schedule=assignment.schedule or {}
        frequency=schedule.get('frequency','once')
        if frequency=='once':
            if timedelta(0)<=now-due<timedelta(minutes=15):
                yield f'assignment:{assignment.id}:{due.isoformat()}'
            continue
        local_due=due.astimezone(local.tzinfo)
        days=(day-local_due.date()).days
        if days<0 or (frequency=='weekly' and days%7):
            continue
        # Keep reminding on calendar slots while a prior occurrence is overdue.
        # Do not silently move its deadline or invent a completed response.
        for clock in schedule.get('times') or [local_due.strftime('%H:%M')]:
            planned=slot(clock)
            if planned and planned>=due:
                yield f'assignment:{assignment.id}:{planned.isoformat()}'

def send_due_reminders(db:Session,now=None):
    if not settings.vapid_public_key or not settings.vapid_private_key:
        return 0
    now=now or utcnow()
    sent=0
    for patient in db.scalars(select(Patient)):
        subscriptions=db.scalars(select(PushSubscription).where(PushSubscription.user_id==patient.id)).all()
        if not subscriptions:
            continue
        for key in reminder_slots(db,patient,now):
            row=db.scalar(select(Reminder).where(Reminder.key==key))
            if row and (row.status=='sent' or row.attempts>=3):
                continue
            if not row:
                row=Reminder(patient_id=patient.id,key=key)
                db.add(row)
                db.flush()
            row.attempts+=1
            successful=False
            for subscription in subscriptions:
                try:
                    webpush(subscription_info={'endpoint':subscription.endpoint,'keys':subscription.keys},
                            data=json.dumps({'title':'Clinical Compass','body':'У вас есть запланированное задание. Откройте приложение.','url':'/'}),
                            vapid_private_key=settings.vapid_private_key,vapid_claims={'sub':settings.vapid_contact},timeout=10,ttl=900)
                    successful=True
                except WebPushException as error:
                    if error.response is not None and error.response.status_code in (404,410):
                        db.delete(subscription)
                except (ValueError,OSError):
                    pass
            row.status='sent' if successful else 'failed'
            if successful:
                row.sent_at=now
                sent+=1
            db.commit()
    return sent
