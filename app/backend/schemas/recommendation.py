from typing import Literal

from pydantic import BaseModel, Field, StrictInt


class RecommendationRequest(BaseModel):
    answers: list[StrictInt] = Field(
        min_length=5,
        max_length=5,
    )

    urgent_help_requested: bool = False


class RecommendationItem(BaseModel):
    code: str

    category: Literal[
        "mandatory",
        "desirable",
    ]

    title: str
    description: str
    source: str


class RecommendationResponse(BaseModel):
    recommendations: list[RecommendationItem]