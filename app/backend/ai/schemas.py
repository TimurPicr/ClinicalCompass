import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

CRITICAL_ASSESSMENT_NOTICE = 'Требуется срочная оценка специалистом.'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Citation(StrictModel):
    id: int
    title: str = Field(max_length=500)
    url: str = Field(max_length=2000)
    page: int | None = None


class Risk(StrictModel):
    level: Literal['yellow', 'red']
    description: str = Field(min_length=1, max_length=2000)
    evidence: list[str] = Field(min_length=1, max_length=10,
                                description='Обязательный непустой список точных строк из patient.evidence_refs, например alert:3 или diary:12. Не свободный текст.')


class AnalysisResult(StrictModel):
    summary: str = Field(min_length=1, max_length=4000,
                         description='Сводка для врача: конкретные факты, даты, динамика и неопределённость.')
    patient_summary: str = Field(min_length=1, max_length=2000,
                                 description='Отдельный понятный пациенту текст без назначения и изменения лечения. При известном красном сигнале сообщает о срочной оценке.')
    facts: list[str] = Field(default_factory=list, max_length=30,
                            description='Факты с датами/значениями. Отличай подтверждённую карту от слов пациента; отражай противоречия между ними.')
    hypotheses: list[str] = Field(default_factory=list, max_length=15)
    recommendations: list[str] = Field(default_factory=list, max_length=15)
    changes: list[str] = Field(default_factory=list, max_length=20,
                              description='Только наблюдаемые изменения от более ранней даты к более поздней, без причинных гипотез и лечебных советов.')
    risks: list[Risk] = Field(default_factory=list, max_length=15,
                            description='Конкретные актуальные основания для дополнительной оценки с точными evidence_refs; известный диагноз сам по себе не новый риск.')
    explanation: str = Field(max_length=4000)
    sources: list[Citation] = Field(default_factory=list, max_length=8)


def analysis_schema(snapshot: dict) -> type[AnalysisResult]:
    """Constrain generation to this snapshot without changing the result shape.

    These constraints guide Ollama's JSON grammar and validate its response;
    provenance and critical coverage must still pass the runtime validators.
    """
    refs = tuple(dict.fromkeys(snapshot.get('evidence_refs', [])))
    risk_description = AnalysisResult.model_fields['risks'].description
    if refs:
        reference_type = Literal[refs]
        grounded_risk = create_model(
            'GroundedRisk', __base__=Risk,
            evidence=(list[reference_type], Field(
                min_length=1, max_length=10, description=Risk.model_fields['evidence'].description)),
        )
        risk_field = (list[grounded_risk], Field(default_factory=list, max_length=15,
                                               description=risk_description))
    else:
        # An empty enum is not a useful generation grammar. With no evidence
        # available, the only valid risk list is empty (or the default []).
        risk_field = (list[Risk], Field(default_factory=list, max_length=0,
                                      description=risk_description))
    fields = {'risks': risk_field}
    if any(alert.get('level') == 'red' for alert in snapshot.get('active_alerts', [])):
        fields['patient_summary'] = (str, Field(
            min_length=1, max_length=2000,
            # llama.cpp's JSON grammar supports a regex subset: escaped
            # spaces and \s/\S may fall back to an unconstrained string.
            # Generate the safety notice as a single paragraph instead.
            pattern='^' + re.escape(CRITICAL_ASSESSMENT_NOTICE).replace(r'\ ', ' ') + r'.*$',
            description=AnalysisResult.model_fields['patient_summary'].description,
        ))
    return create_model('GroundedAnalysisResult', __base__=AnalysisResult, **fields)


class MedicalFact(StrictModel):
    category: Literal['indication', 'adverse_effect', 'contraindication', 'interaction', 'other']
    statement: str = Field(max_length=1200)
    quote: str = Field(min_length=1, max_length=1500)


class FactResult(StrictModel):
    facts: list[MedicalFact] = Field(default_factory=list, max_length=12)


class Proposal(StrictModel):
    field: Literal['diagnosis', 'comorbidities', 'history', 'allergies', 'examinations', 'treatment_history']
    value: str = Field(min_length=1, max_length=3000)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=1500)


class DocumentResult(StrictModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=30)


def validate_citations(result: AnalysisResult, retrieved: list[dict]) -> AnalysisResult:
    """Never accept URLs or source identifiers invented by a model."""
    allowed = {item['id']: item for item in retrieved}
    for citation in result.sources:
        source = allowed.get(citation.id)
        if source is None:
            raise ValueError('Модель сослалась на источник вне найденного контекста')
        if citation.url != source['url'] or citation.page != source.get('page'):
            raise ValueError('Ссылка модели не соответствует исходному фрагменту')
        citation.title = source['title']
    return result


def validate_analysis_evidence(result: AnalysisResult, snapshot: dict) -> AnalysisResult:
    """Check event provenance and known critical coverage, not medical truth."""
    allowed = set(snapshot.get('evidence_refs', []))
    for risk in result.risks:
        if not risk.evidence or any(ref not in allowed for ref in risk.evidence):
            raise ValueError('Риск AI не привязан к доступным событиям пациента')
    covered = {ref for risk in result.risks if risk.level == 'red' for ref in risk.evidence}
    for alert in snapshot.get('active_alerts', []):
        if alert['level'] == 'red' and f'alert:{alert["id"]}' not in covered:
            raise ValueError('AI пропустил активный критический сигнал правил')
        if alert['level'] == 'red' and not result.patient_summary.startswith(CRITICAL_ASSESSMENT_NOTICE):
            raise ValueError('Пациентская сводка AI не сообщает о необходимости срочной оценки')
    return result
