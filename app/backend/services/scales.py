"""Registry of scoring algorithms. Definitions are immutable per version.

    New clinically validated scales require reviewed definitions in an Alembic
    migration and a registered, tested scorer. No endpoint activates unknown rules.
"""
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import select

from app.backend.core.security import patient_access
from app.backend.services.alert_rules import evaluate_reviewed_rules
from app.backend.models.clinical import Scale, QuestionnaireResult, Recommendation
from app.backend.schemas.questionnaire import QuestionnaireSubmission
from app.backend.schemas.recommendation import RecommendationRequest
from app.backend.services.questionnaire_service import calculate_score
from app.backend.services.recommendations.recommendation_service import generate_recommendations
from app.backend.services.workflows import audit

DEMO_NOTE = "Результат учебного опросника. Не предназначен для медицинской диагностики."


@dataclass(frozen=True)
class Scored:
    score: int
    max_score: int
    note: str


def score_demo(answers):
    QuestionnaireSubmission(answers=answers)
    return Scored(calculate_score(answers), 15, DEMO_NOTE)


SCORERS = {"demo_sum_v1": score_demo}


def submit_scale(db, user, code, version, answers, *, commit=True):
    patient = patient_access(db, user, user.id, lock=True)
    scale = db.scalar(select(Scale).where(Scale.code == code, Scale.version == version))
    if not scale or not scale.active or scale.scoring_key not in SCORERS or scale.review_status not in {"demo_only", "validated"}:
        raise HTTPException(409, "Шкала не активирована или ожидает клинической проверки")
    # Existing demo validation and scorer remain the single implementation.
    if len(answers) != len(scale.questions) or any(
        answer < 0 or answer >= len(question["options"])
        for answer, question in zip(answers, scale.questions)
    ):
        raise HTTPException(422, "Число ответов или варианты не соответствуют версии шкалы")
    scored = SCORERS[scale.scoring_key](answers)
    result = QuestionnaireResult(patient_id=user.id, scale_id=scale.id, scale_code=code,
                                 scale_version=version, answers=answers,
                                 score=scored.score, max_score=scored.max_score,
                                 note=scored.note)
    db.add(result)
    db.flush()
    if code == "demo" and version == "1":
        for item in generate_recommendations(RecommendationRequest(answers=answers)):
            db.add(Recommendation(patient_id=user.id, result_id=result.id, **item.model_dump(),
                                  rule_version="demo_rule_v1", explanation=item.description))
    evaluate_reviewed_rules(db, patient, result)
    audit(db, user.id, user.id, "questionnaire_result", result.id, "submitted")
    if commit:
        db.commit()
        db.refresh(result)
    return result
