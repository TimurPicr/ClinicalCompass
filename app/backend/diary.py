"""Fixed-direction wellbeing diary and its doctor-defined local-time schedule."""
from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.backend.auth import current_user, doctor_user, accessible_patient
from app.backend.clinical_common import Input, ScheduleInput, row_dict, lock_patient, patient_only
from app.backend.monitoring import record_event
from database.connection import get_db
from database.models import Audit, Diary, User

router = APIRouter()


class DiaryInput(Input):
    mood: int = Field(ge=0, le=10, strict=True)
    anxiety: int = Field(ge=0, le=10, strict=True)
    sleep: int = Field(ge=0, le=10, strict=True)
    energy: int = Field(ge=0, le=10, strict=True)
    wellbeing: int = Field(ge=0, le=10, strict=True)
    comment: str = Field(default='', max_length=5000)


@router.get('/patients/{patient_id}/diary')
def list_diary(patient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    accessible_patient(db, user, patient_id)
    return [row_dict(d) for d in db.scalars(select(Diary).where(Diary.patient_id == patient_id).order_by(Diary.created_at))]


@router.post('/patients/{patient_id}/diary', status_code=201)
def create_diary(patient_id: int, payload: DiaryInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patient_only(user)
    lock_patient(db, user, patient_id)
    entry = Diary(patient_id=patient_id, **payload.model_dump())
    db.add(entry)
    db.flush()
    record_event(db, patient_id, f'diary:{entry.id}')
    db.commit()
    return row_dict(entry)


@router.put('/patients/{patient_id}/diary-schedule')
def diary_schedule(patient_id: int, payload: ScheduleInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    patient = lock_patient(db, user, patient_id)
    before = patient.diary_times
    patient.diary_times = payload.times
    db.add(Audit(patient_id=patient_id, actor_id=user.id, entity='diary_schedule', entity_id=patient_id, before={'times': before}, after={'times': payload.times}))
    db.commit()
    return {'times': patient.diary_times}
