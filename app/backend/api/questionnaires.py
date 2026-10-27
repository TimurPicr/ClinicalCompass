from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.backend.core.time import as_utc
from app.backend.core.security import Auth, DB, patient_access, require_patient
from app.backend.models.clinical import Scale, QuestionnaireResult
from app.backend.schemas.questionnaire import Questionnaire, QuestionnaireSubmission, ScaleSubmission
from app.backend.services.questionnaire_service import get_demo_questionnaire
from app.backend.services.scales import submit_scale

router = APIRouter(prefix="/api", tags=["Questionnaires"])


@router.get("/questionnaires/demo", response_model=Questionnaire)
def get_questionnaire():
    return get_demo_questionnaire()


@router.get("/scales")
def scales(user: Auth, db: DB):
    return db.scalars(select(Scale).order_by(Scale.id)).all()


@router.post("/questionnaires/demo/submit")
def submit_questionnaire(submission: QuestionnaireSubmission, user: Auth, db: DB):
    require_patient(user)
    return submit_scale(db, user, "demo", "1", submission.answers)


@router.post("/scales/{code}/{version}/submit")
def submit(code: str, version: str, submission: ScaleSubmission, user: Auth, db: DB):
    require_patient(user)
    return submit_scale(db, user, code, version, submission.answers)


def filtered_results(db, patient_id, scale, version, start, end):
    start = as_utc(start) if start else None
    end = as_utc(end) if end else None
    if start and end and start > end:
        raise HTTPException(422, "Начало периода позже окончания")
    query = select(QuestionnaireResult).where(QuestionnaireResult.patient_id == patient_id)
    if scale:
        query = query.where(QuestionnaireResult.scale_code == scale)
    if version:
        query = query.where(QuestionnaireResult.scale_version == version)
    if start:
        query = query.where(QuestionnaireResult.created_at >= start)
    if end:
        query = query.where(QuestionnaireResult.created_at <= end)
    return db.scalars(query.order_by(QuestionnaireResult.created_at, QuestionnaireResult.id)).all()


@router.get("/patients/{patient_id}/results")
def history(patient_id: int, user: Auth, db: DB, scale: str | None = None,
            version: str | None = None, start: datetime | None = None, end: datetime | None = None):
    patient_access(db, user, patient_id)
    return filtered_results(db, patient_id, scale, version, start, end)


@router.get("/patients/{patient_id}/series")
def series(patient_id: int, user: Auth, db: DB, scale: str | None = None,
           version: str | None = None, start: datetime | None = None, end: datetime | None = None):
    patient_access(db, user, patient_id)
    grouped = {}
    for row in filtered_results(db, patient_id, scale, version, start, end):
        key = (row.scale_code, row.scale_version)
        grouped.setdefault(key, []).append({"result_id": row.id, "at": row.created_at, "score": row.score, "max_score": row.max_score})
    return [{"scale": key[0], "version": key[1], "points": points} for key, points in grouped.items()]
