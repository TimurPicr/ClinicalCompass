from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.backend.core.time import REPORT_ZONE, as_utc
from app.backend.core.security import Auth, DB, patient_access, require_doctor, require_patient
from app.backend.models.clinical import AdherenceReport, AdverseEvent, Message
from app.backend.schemas.clinical import ReportInput, AdverseInput, Comment, MessageInput
from app.backend.services.workflows import audit, create_alert, patient_plan

router = APIRouter(prefix="/api/patients", tags=["Follow-up"])


@router.get("/{patient_id}/adherence")
def adherence(patient_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    return db.scalars(select(AdherenceReport).where(AdherenceReport.patient_id == patient_id).order_by(AdherenceReport.report_date.desc(), AdherenceReport.id.desc())).all()


@router.get("/{patient_id}/adherence/summary")
def adherence_summary(patient_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    rows = db.scalars(select(AdherenceReport).where(AdherenceReport.patient_id == patient_id)).all()
    counts = {status: sum(row.status == status for row in rows) for status in ["completed", "missed", "partial"]}
    return {"total": len(rows), **counts, "basis": "patient_self_report"}


@router.post("/{patient_id}/adherence", status_code=201)
def report(patient_id: int, data: ReportInput, user: Auth, db: DB):
    require_patient(user)
    patient_access(db, user, patient_id, lock=True)
    plan = patient_plan(db, patient_id, data.plan_id)
    if plan.status != "active" or data.report_date < as_utc(plan.confirmed_at).astimezone(REPORT_ZONE).date():
        raise HTTPException(409, "Отчёт допустим для действующего плана с даты подтверждения")
    item = AdherenceReport(patient_id=patient_id, **data.model_dump(exclude={"report_date"}),
                           report_date=data.report_date.isoformat())
    db.add(item)
    try:
        db.flush()
        audit(db, user.id, patient_id, "adherence_report", item.id, "self_reported")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Отчёт за эту дату уже существует") from None
    db.refresh(item)
    return item


@router.get("/{patient_id}/adverse-events")
def adverse_events(patient_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    return db.scalars(select(AdverseEvent).where(AdverseEvent.patient_id == patient_id).order_by(AdverseEvent.id.desc())).all()


@router.post("/{patient_id}/adverse-events", status_code=201)
def adverse(patient_id: int, data: AdverseInput, user: Auth, db: DB):
    require_patient(user)
    patient = patient_access(db, user, patient_id, lock=True)
    if not patient.doctor_id:
        raise HTTPException(409, "Сначала прикрепитесь к врачу")
    if data.plan_id:
        patient_plan(db, patient_id, data.plan_id)
    item = AdverseEvent(patient_id=patient_id, **data.model_dump(exclude={"onset_date"}),
                       onset_date=data.onset_date.isoformat())
    db.add(item)
    db.flush()
    create_alert(db, patient, "adverse_event_reported", f"adverse:{item.id}",
                 "Пациент сообщил о нежелательном явлении", severity="info")
    audit(db, user.id, patient_id, "adverse_event", item.id, "reported")
    db.commit()
    db.refresh(item)
    return item


@router.post("/{patient_id}/adverse-events/{event_id}/review")
def review_event(patient_id: int, event_id: int, data: Comment, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id)
    item = db.scalar(select(AdverseEvent).where(AdverseEvent.id == event_id, AdverseEvent.patient_id == patient_id).with_for_update())
    if not item:
        raise HTTPException(404, "Событие не найдено")
    if item.status != "pending":
        raise HTTPException(409, "Событие уже рассмотрено")
    item.status, item.comment = "reviewed", data.comment
    item.reviewed_by, item.reviewed_at = user.id, datetime.now(timezone.utc)
    audit(db, user.id, patient_id, "adverse_event", item.id, "reviewed", {"comment": data.comment})
    db.commit()
    db.refresh(item)
    return item


@router.get("/{patient_id}/messages")
def messages(patient_id: int, user: Auth, db: DB, after_id: int = Query(default=0, ge=0)):
    patient = patient_access(db, user, patient_id)
    # A future reassignment must not disclose a previous doctor's conversation.
    return db.scalars(select(Message).where(Message.patient_id == patient_id, Message.doctor_id == patient.doctor_id,
                     Message.id > after_id).order_by(Message.id)).all()


@router.post("/{patient_id}/messages", status_code=201)
def send_message(patient_id: int, data: MessageInput, user: Auth, db: DB):
    patient = patient_access(db, user, patient_id, lock=True)
    if not patient.doctor_id:
        raise HTTPException(409, "Нет ведущего врача")
    item = Message(patient_id=patient_id, doctor_id=patient.doctor_id, sender_id=user.id, text=data.text)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
