from fastapi import APIRouter

from app.backend.schemas.questionnaire import (
    Questionnaire,
    QuestionnaireSubmission,
    QuestionnaireResult,
)

from app.backend.services.questionnaire_service import (
    get_demo_questionnaire,
    calculate_score,
)


router = APIRouter(
    prefix="/api/questionnaires",
    tags=["Questionnaires"],
)


@router.get(
    "/demo",
    response_model=Questionnaire,
)
def get_questionnaire():
    return get_demo_questionnaire()


@router.post(
    "/demo/submit",
    response_model=QuestionnaireResult,
)
def submit_questionnaire(
    submission: QuestionnaireSubmission,
):
    score = calculate_score(submission.answers)

    return QuestionnaireResult(
        score=score,
        max_score=15,
        note=(
            "Результат учебного опросника. "
            "Не предназначен для медицинской диагностики."
        ),
    )