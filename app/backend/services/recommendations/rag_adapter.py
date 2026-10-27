"""Optional adapter to the existing recomendation.py; no new inference engine.

The legacy service must stay private. Citations are stored for physician review,
not treated as validated clinical rules. No patient history is sent implicitly.
"""
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictInt, ValidationError

from app.backend.core.config import settings


class Source(BaseModel):
    id: StrictInt
    document: str = Field(min_length=1, max_length=255)
    page: int = Field(gt=0)


class Draft(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)
    source_ids: list[StrictInt]
    sources: list[Source]
    missing_information: list[str]
    requires_doctor_review: bool


def ask_existing_rag(question: str):
    if not settings.rag_enabled:
        raise HTTPException(409, "RAG отключён: необходимы локальный сервис, проверенные документы и экспертная проверка")
    try:
        response = httpx.post(settings.rag_service_url, json={"question": question}, timeout=90)
        response.raise_for_status()
        draft = Draft.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError):
        raise HTTPException(502, "Сервис RAG недоступен или вернул некорректные данные") from None
    sources = [s.model_dump() for s in draft.sources if s.id in draft.source_ids]
    if not sources or not draft.requires_doctor_review:
        raise HTTPException(409, "Черновик без проверяемых ссылок не может быть сохранён как предложение")
    return draft, sources
