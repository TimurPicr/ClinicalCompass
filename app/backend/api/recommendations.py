from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.backend.core.security import Auth, DB, patient_access, require_doctor
from app.backend.models.clinical import Recommendation
from app.backend.schemas.clinical import Review, RagQuestion
from app.backend.services.recommendations.rag_adapter import ask_existing_rag
from app.backend.schemas.recommendation import RecommendationRequest, RecommendationResponse
from app.backend.services.recommendations.recommendation_service import generate_recommendations
from app.backend.services.workflows import audit

router = APIRouter(prefix="/api", tags=["Recommendations"])


@router.post("/recommendations/preview", response_model=RecommendationResponse)
def preview_recommendations(request: RecommendationRequest, user: Auth):
    require_doctor(user)
    if any(answer < 0 or answer > 3 for answer in request.answers):
        raise HTTPException(422, "Ответы должны находиться в диапазоне 0–3")
    return RecommendationResponse(recommendations=generate_recommendations(request))


@router.get("/patients/{patient_id}/recommendations")
def history(patient_id: int, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id)
    return db.scalars(select(Recommendation).where(Recommendation.patient_id == patient_id).order_by(Recommendation.id.desc())).all()


@router.post("/patients/{patient_id}/recommendations/{recommendation_id}/review")
def review(patient_id: int, recommendation_id: int, data: Review, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id)
    item = db.scalar(select(Recommendation).where(Recommendation.id == recommendation_id,
                     Recommendation.patient_id == patient_id).with_for_update())
    if not item:
        raise HTTPException(404, "Рекомендация не найдена")
    if item.status != "pending":
        raise HTTPException(409, "Рекомендация уже рассмотрена")
    item.status, item.review_comment = data.status, data.comment
    item.reviewed_by, item.reviewed_at = user.id, datetime.now(timezone.utc)
    audit(db, user.id, patient_id, "recommendation", item.id, data.status, {"comment": data.comment})
    db.commit()
    db.refresh(item)
    return item


@router.post("/patients/{patient_id}/recommendations/generate-rag", status_code=201)
def generate_rag(patient_id: int, data: RagQuestion, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id)
    draft, sources = ask_existing_rag(data.question)
    recommendation = Recommendation(
        patient_id=patient_id, result_id=None, code="legacy_rag_draft",
        title="Черновик существующей RAG-системы — требуется проверка",
        description=draft.answer, category="desirable", source="recomendation.py / PDF corpus",
        rule_version="legacy_rag_v1:qwen3:8b", explanation=draft.answer,
        evidence={"sources": sources, "missing_information": draft.missing_information,
                  "clinical_validation": "pending", "requires_doctor_review": True},
    )
    db.add(recommendation)
    db.flush()
    audit(db, user.id, patient_id, "recommendation", recommendation.id, "rag_draft_generated")
    db.commit()
    db.refresh(recommendation)
    return recommendation
