from app.backend.schemas.recommendation import (
    RecommendationItem,
    RecommendationRequest,
)

from app.backend.services.recommendations.rules import (
    check_sleep_problems,
    check_concentration_problems,
    check_urgent_request,
)


def generate_recommendations(
    request: RecommendationRequest,
) -> list[RecommendationItem]:

    recommendations = []

    rules = [
        check_sleep_problems,
        check_concentration_problems,
    ]

    for rule in rules:
        recommendation = rule(request.answers)

        if recommendation is not None:
            recommendations.append(recommendation)

    urgent_recommendation = check_urgent_request(
        request.urgent_help_requested
    )

    if urgent_recommendation is not None:
        recommendations.append(urgent_recommendation)

    return recommendations