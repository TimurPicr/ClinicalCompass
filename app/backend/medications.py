"""Doctor prescriptions, immutable treatment versions and actual patient intake."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.backend.auth import current_user, doctor_user, accessible_patient
from app.backend.clinical_common import Input, ScheduleInput, row_dict, lock_patient, patient_only
from app.backend.monitoring import record_event
from database.connection import get_db
from database.models import Audit, Intake, Prescription, PrescriptionVersion, User, utcnow

router = APIRouter()


class PrescriptionInput(Input):
    name: str = Field(min_length=1, max_length=200)
    substance: str = Field(default='', max_length=200)
    dose: str = Field(min_length=1, max_length=100)
    unit: str = Field(default='мг', min_length=1, max_length=40)
    times: list[str]
    start_date: date
    end_date: date | None = None
    comment: str = Field(default='', max_length=5000)
    active: bool = True

    @field_validator('times')
    @classmethod
    def check_times(cls, value):
        return ScheduleInput(times=value).times

    @model_validator(mode='after')
    def check_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError('Окончание назначения раньше начала')
        return self


class IntakeInput(Input):
    scheduled_at: datetime
    actual_at: datetime | None = None
    status: Literal['taken', 'skipped', 'missed']
    reason: str = Field(default='', max_length=3000)
    side_effect: str = Field(default='', max_length=3000)
    severity: int = Field(default=0, ge=0, le=10, strict=True)

    @field_validator('scheduled_at', 'actual_at')
    @classmethod
    def timestamps(cls, value):
        if value and value.tzinfo is None:
            raise ValueError('Укажите часовой пояс времени приёма')
        if value and value > utcnow() + timedelta(minutes=5):
            raise ValueError('Нельзя отметить будущий приём')
        return value.astimezone(timezone.utc) if value else value

    @model_validator(mode='after')
    def check_status(self):
        if self.status in {'skipped', 'missed'} and not self.reason.strip():
            raise ValueError('Укажите причину пропуска')
        if self.status in {'skipped', 'missed'} and self.actual_at:
            raise ValueError('Для пропуска фактическое время не указывается')
        if self.severity and not self.side_effect.strip():
            raise ValueError('Опишите предполагаемый побочный эффект')
        return self


def prescription_dict(db, prescription):
    result = row_dict(prescription)
    versions = list(db.scalars(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription.id).order_by(PrescriptionVersion.version)))
    result['versions'] = [row_dict(v) for v in versions]
    result['data'] = deepcopy(versions[-1].data) if versions else {}
    result['intakes'] = [row_dict(i) for i in db.scalars(select(Intake).where(Intake.prescription_id == prescription.id).order_by(Intake.scheduled_at.desc()))]
    return result


@router.get('/patients/{patient_id}/prescriptions')
def list_prescriptions(patient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    accessible_patient(db, user, patient_id)
    return [prescription_dict(db, p) for p in db.scalars(select(Prescription).where(Prescription.patient_id == patient_id).order_by(Prescription.id.desc()))]


@router.post('/patients/{patient_id}/prescriptions', status_code=201)
def create_prescription(patient_id: int, payload: PrescriptionInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    lock_patient(db, user, patient_id)
    prescription = Prescription(patient_id=patient_id, doctor_id=user.id, current_version=1, active=payload.active)
    db.add(prescription)
    db.flush()
    data = payload.model_dump(mode='json', exclude={'active'})
    db.add(PrescriptionVersion(prescription_id=prescription.id, version=1, data=data))
    db.add(Audit(patient_id=patient_id, actor_id=user.id, entity='prescription', entity_id=prescription.id, before={}, after={**data, 'active': prescription.active, 'version': 1}))
    record_event(db, patient_id, f'prescription:{prescription.id}:1')
    db.commit()
    return prescription_dict(db, prescription)


@router.put('/prescriptions/{prescription_id}')
def update_prescription(prescription_id: int, payload: PrescriptionInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    prescription = db.get(Prescription, prescription_id)
    if not prescription:
        raise HTTPException(404, 'Назначение не найдено')
    lock_patient(db, user, prescription.patient_id)
    prescription = db.scalar(select(Prescription).where(Prescription.id == prescription_id).with_for_update()
                             .execution_options(populate_existing=True))
    previous = db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription_id, PrescriptionVersion.version == prescription.current_version))
    before = {**deepcopy(previous.data), 'active': prescription.active, 'version': prescription.current_version}
    prescription.current_version += 1
    prescription.active = payload.active
    data = payload.model_dump(mode='json', exclude={'active'})
    db.add(PrescriptionVersion(prescription_id=prescription_id, version=prescription.current_version, data=data))
    db.add(Audit(patient_id=prescription.patient_id, actor_id=user.id, entity='prescription', entity_id=prescription_id, before=before, after={**data, 'active': prescription.active, 'version': prescription.current_version}))
    record_event(db, prescription.patient_id, f'prescription:{prescription.id}:{prescription.current_version}')
    db.commit()
    return prescription_dict(db, prescription)


@router.post('/prescriptions/{prescription_id}/intakes', status_code=201)
def create_intake(prescription_id: int, payload: IntakeInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patient_only(user)
    prescription = db.get(Prescription, prescription_id)
    if not prescription:
        raise HTTPException(404, 'Назначение не найдено')
    lock_patient(db, user, prescription.patient_id)
    prescription = db.scalar(select(Prescription).where(Prescription.id == prescription_id).with_for_update()
                             .execution_options(populate_existing=True))
    # Resolve the historically applicable version, including records before a change.
    version = db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription_id, PrescriptionVersion.created_at <= payload.scheduled_at).order_by(PrescriptionVersion.version.desc()).limit(1))
    if not version:
        # The initial version has a date-only clinical start, so a doctor can
        # document treatment already started earlier that day. Later changes
        # become effective at their exact version timestamp.
        version = db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription_id, PrescriptionVersion.version == 1))
    if not version:
        raise HTTPException(422, 'Версия назначения не найдена')
    local = payload.scheduled_at.astimezone(ZoneInfo(user.timezone))
    data = version.data
    if local.date() < date.fromisoformat(data['start_date']) or (data.get('end_date') and local.date() > date.fromisoformat(data['end_date'])) or local.strftime('%H:%M') not in data['times'] or local.second or local.microsecond:
        raise HTTPException(422, 'Время не соответствует расписанию действовавшей версии назначения')
    if not prescription.active:
        raise HTTPException(409, 'Назначение завершено')
    if db.scalar(select(Intake).where(Intake.prescription_id == prescription_id, Intake.scheduled_at == payload.scheduled_at)):
        raise HTTPException(409, 'Этот приём уже отмечен')
    values = payload.model_dump()
    values['status'] = 'skipped' if payload.status == 'missed' else payload.status
    if payload.status == 'taken' and payload.actual_at is None:
        values['actual_at'] = utcnow()
    intake = Intake(patient_id=prescription.patient_id, prescription_id=prescription_id, version=version.version, **values)
    db.add(intake)
    db.flush()
    record_event(db, prescription.patient_id, f'intake:{intake.id}')
    db.commit()
    return row_dict(intake)
