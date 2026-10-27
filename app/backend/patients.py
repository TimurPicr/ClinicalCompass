"""Patient overview and confirmed/reported medical records with audit history."""
from copy import deepcopy
from datetime import date
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.backend.auth import current_user, accessible_patient
from app.backend.clinical_common import Input, aware, row_dict, lock_patient
from app.backend.monitoring import record_event
from database.connection import get_db
from database.models import Assignment, Audit, Patient, User, utcnow

router = APIRouter()


class RecordInput(Input):
    data: dict[str, str | list | dict | None]
    birth_date: date | None = None

    @field_validator('data')
    @classmethod
    def record_fields(cls, value):
        allowed = {'diagnosis', 'diagnosis_code', 'comorbidities', 'anamnesis', 'allergies', 'treatment_history', 'examinations', 'notes'}
        if set(value) - allowed:
            raise ValueError('Неизвестное поле медицинской карты')
        if len(str(value)) > 60000:
            raise ValueError('Медицинская карта слишком велика')
        code = value.get('diagnosis_code')
        if code and (not isinstance(code, str) or not re.fullmatch(r'F\d{2}(?:\.\d{1,2})?', code.upper())):
            raise ValueError('Основной диагноз должен иметь код F00–F99 по МКБ-10')
        return value

    @field_validator('birth_date')
    @classmethod
    def valid_birth(cls, value):
        if value and (value > utcnow().date() or value.year < 1900):
            raise ValueError('Проверьте дату рождения')
        return value


def pending_count(db, patient_id):
    now = utcnow()
    return sum(1 for a in db.scalars(select(Assignment).where(Assignment.patient_id == patient_id, Assignment.active.is_(True))) if aware(a.due_at) <= now)


def patient_dict(db, patient):
    person = db.get(User, patient.id)
    result = row_dict(patient)
    result.pop('record', None)
    result.pop('reported_record', None)
    result.update(name=person.name, email=person.email, timezone=person.timezone,
                  diagnosis=(patient.record or {}).get('diagnosis', ''),
                  diagnosis_code=(patient.record or {}).get('diagnosis_code', ''),
                  pending_assignments=pending_count(db, patient.id))
    return result


@router.get('/patients')
def list_patients(db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = select(Patient).where(Patient.doctor_id == user.id) if user.role == 'doctor' else select(Patient).where(Patient.id == user.id)
    patients = list(db.scalars(query))
    patients.sort(key=lambda p: ({'red': 0, 'yellow': 1, 'green': 2}.get(p.status, 3), p.id))
    return [patient_dict(db, p) for p in patients]


@router.get('/patients/{patient_id}')
def get_patient(patient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return patient_dict(db, accessible_patient(db, user, patient_id))


@router.get('/patients/{patient_id}/record')
def get_record(patient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patient = accessible_patient(db, user, patient_id)
    return {'confirmed': patient.record, 'reported': patient.reported_record,
            'birth_date': patient.birth_date, 'monitoring_started_at': patient.monitoring_started_at,
            'history': [row_dict(a) for a in db.scalars(select(Audit).where(Audit.patient_id == patient_id, Audit.entity.in_(['record', 'reported_record'])).order_by(Audit.created_at.desc()))]}


@router.put('/patients/{patient_id}/record')
def update_record(patient_id: int, payload: RecordInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patient = lock_patient(db, user, patient_id)
    field = 'record' if user.role == 'doctor' else 'reported_record'
    before = deepcopy(getattr(patient, field) or {})
    after = {**before, **payload.data}
    if user.role == 'patient' and ('diagnosis' in payload.data or 'diagnosis_code' in payload.data):
        raise HTTPException(403, 'Диагноз устанавливает врач; исходные сведения внесите в анамнез')
    audit_before, audit_after = deepcopy(before), deepcopy(after)
    if 'birth_date' in payload.model_fields_set:
        audit_before['birth_date'] = patient.birth_date.isoformat() if patient.birth_date else None
        audit_after['birth_date'] = payload.birth_date.isoformat() if payload.birth_date else None
        # Patient-reported birth date is separate until doctor verifies it.
        if user.role == 'doctor':
            patient.birth_date = payload.birth_date
        else:
            after['birth_date'] = audit_after['birth_date']
    setattr(patient, field, after)
    db.add(Audit(patient_id=patient_id, actor_id=user.id, entity=field, entity_id=patient_id, before=audit_before, after=audit_after))
    if user.role == 'patient':
        record_event(db, patient_id, f'record:{utcnow().isoformat()}')
    db.commit()
    return get_record(patient_id, db, user)
