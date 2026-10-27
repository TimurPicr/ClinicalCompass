from datetime import date, datetime, time

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.backend.core.security import Auth, DB, patient_access, require_patient
from app.backend.core.time import REPORT_ZONE
from app.backend.models.clinical import DiaryEntry, DiaryRevision, QuestionnaireResult, utcnow
from app.backend.schemas.clinical import DiaryInput
from app.backend.services.scales import submit_scale
from app.backend.services.workflows import audit

router = APIRouter(prefix="/api/patients", tags=["Diary"])


def serialize(entry, result):
    return {"id": entry.id, "entry_date": entry.entry_date, "text": entry.text,
            "created_at": entry.created_at, "updated_at": entry.updated_at,
            "result_id": result.id, "answers": result.answers, "score": result.score,
            "max_score": result.max_score, "scale_code": result.scale_code,
            "scale_version": result.scale_version}


def entries(db, patient_id, start, end):
    if start and end and start > end:
        raise HTTPException(422, "Начало периода позже окончания")
    query = select(DiaryEntry, QuestionnaireResult).join(QuestionnaireResult, DiaryEntry.result_id == QuestionnaireResult.id).where(DiaryEntry.patient_id == patient_id)
    if start:
        query = query.where(DiaryEntry.entry_date >= start.isoformat())
    if end:
        query = query.where(DiaryEntry.entry_date <= end.isoformat())
    return db.execute(query.order_by(DiaryEntry.entry_date)).all()


@router.get("/{patient_id}/diary")
def history(patient_id: int, user: Auth, db: DB, start: date | None = None, end: date | None = None):
    patient_access(db, user, patient_id)
    return [serialize(entry, result) for entry, result in entries(db, patient_id, start, end)]


@router.post("/{patient_id}/diary")
def save(patient_id: int, data: DiaryInput, user: Auth, db: DB):
    require_patient(user)
    patient_access(db, user, patient_id, lock=True)
    entry = db.scalar(select(DiaryEntry).where(DiaryEntry.patient_id == patient_id, DiaryEntry.entry_date == data.entry_date.isoformat()))
    # Repeated saves of identical content do not create extra results or revisions.
    previous = None
    if entry:
        previous = db.get(QuestionnaireResult, entry.result_id)
        if previous.answers == data.answers and entry.text == data.text:
            return serialize(entry, previous)
    result = previous if previous and previous.answers == data.answers else submit_scale(db, user, "demo", "1", data.answers, commit=False)
    action = "updated" if entry else "created"
    if entry is None:
        entry = DiaryEntry(patient_id=patient_id, entry_date=data.entry_date.isoformat(), result_id=result.id, text=data.text)
        db.add(entry)
    else:
        entry.result_id, entry.text, entry.updated_at = result.id, data.text, utcnow()
    db.flush()
    db.add(DiaryRevision(entry_id=entry.id, result_id=result.id, text=data.text, actor_id=user.id))
    audit(db, user.id, patient_id, "diary_entry", entry.id, action, {"result_id": result.id, "entry_date": entry.entry_date})
    db.commit()
    db.refresh(entry)
    return serialize(entry, result)


@router.get("/{patient_id}/diary/series")
def series(patient_id: int, user: Auth, db: DB, start: date | None = None, end: date | None = None):
    patient_access(db, user, patient_id)
    groups = {}
    for entry, result in entries(db, patient_id, start, end):
        key = (result.scale_code, result.scale_version)
        groups.setdefault(key, []).append({"result_id": result.id,
            "at": datetime.combine(date.fromisoformat(entry.entry_date), time(), tzinfo=REPORT_ZONE),
            "score": result.score, "max_score": result.max_score})
    return [{"scale": key[0], "version": key[1], "points": points} for key, points in groups.items()]


@router.get("/{patient_id}/diary/{entry_id}/revisions")
def revisions(patient_id: int, entry_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    entry = db.get(DiaryEntry, entry_id)
    if not entry or entry.patient_id != patient_id:
        raise HTTPException(404, "Запись не найдена")
    return db.scalars(select(DiaryRevision).where(DiaryRevision.entry_id == entry.id).order_by(DiaryRevision.id)).all()
