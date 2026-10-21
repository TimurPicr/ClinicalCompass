from fastapi import APIRouter, HTTPException

from app.backend.schemas.recommendation import (
    RecommendationRequest,
    RecommendationResponse,
)

from app.backend.services.recommendations.recommendation_service import (
    generate_recommendations,
)


router = APIRouter(
    prefix="/api/recommendations",
    tags=["Recommendations"],
)


@router.post(
    "/preview",
    response_model=RecommendationResponse,
)
def preview_recommendations(
    request: RecommendationRequest,
):

    if any(
        answer < 0 or answer > 3
        for answer in request.answers
    ):
        raise HTTPException(
            status_code=422,
            detail="Ответы должны находиться в диапазоне 0–3",
        )

    recommendations = generate_recommendations(
        request
    )

    return RecommendationResponse(
        recommendations=recommendations
    )