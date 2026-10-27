"""Patient-specific generation constraints; no model output is substituted."""
import json

import pytest
from pydantic import ValidationError

from app.backend.ai.schemas import (AnalysisResult, CRITICAL_ASSESSMENT_NOTICE,
                                    analysis_schema, validate_analysis_evidence)


def response(**overrides):
    return {
        'summary': 'Наблюдение требует оценки врача.',
        'patient_summary': 'Обсудите изменения с врачом.',
        'facts': [], 'hypotheses': [], 'recommendations': [], 'changes': [],
        'risks': [], 'explanation': 'Основания ограничены доступными данными.', 'sources': [],
        **overrides,
    }


@pytest.mark.parametrize('evidence', [[], ['diary:999'], ['diary:1', 'intake:999']])
def test_generation_schema_rejects_empty_or_unknown_risk_references(evidence):
    schema = analysis_schema({'evidence_refs': ['diary:1', 'alert:3'], 'active_alerts': []})
    with pytest.raises(ValidationError):
        schema.model_validate(response(risks=[{
            'level': 'yellow', 'description': 'Изменение самочувствия', 'evidence': evidence,
        }]))


def test_generation_schema_preserves_external_shape_and_allows_exact_patient_references():
    snapshot = {'evidence_refs': ['diary:1', 'alert:3', 'diary:1'], 'active_alerts': []}
    schema = analysis_schema(snapshot)
    payload = response(risks=[{'level': 'yellow', 'description': 'Изменение самочувствия',
                               'evidence': ['diary:1', 'alert:3']}])
    result = schema.model_validate_json(json.dumps(payload, ensure_ascii=False))
    assert isinstance(result, AnalysisResult)
    assert result.model_dump() == payload
    validate_analysis_evidence(result, snapshot)
    exported = json.loads(json.dumps(schema.model_json_schema(), ensure_ascii=False))
    evidence = exported['$defs']['GroundedRisk']['properties']['evidence']
    assert evidence['items']['enum'] == ['diary:1', 'alert:3']
    assert evidence['minItems'] == 1 and evidence['maxItems'] == 10
    assert exported['additionalProperties'] is False


def test_generation_schema_without_evidence_cannot_invent_a_risk():
    schema = analysis_schema({'evidence_refs': [], 'active_alerts': []})
    assert schema.model_validate(response()).risks == []
    assert schema.model_json_schema()['properties']['risks']['maxItems'] == 0
    with pytest.raises(ValidationError):
        schema.model_validate(response(risks=[{
            'level': 'red', 'description': 'Выдуманный риск', 'evidence': ['diary:1'],
        }]))


@pytest.mark.parametrize('prefix', ['', 'Обсудите с врачом. ', ' Требуется срочная оценка специалистом. '])
def test_generation_schema_requires_exact_urgency_prefix_for_known_red(prefix):
    snapshot = {'evidence_refs': ['alert:3'], 'active_alerts': [{'id': 3, 'level': 'red'}]}
    schema = analysis_schema(snapshot)
    with pytest.raises(ValidationError):
        schema.model_validate(response(patient_summary=prefix + 'Доступны новые записи.'))
    accepted = schema.model_validate(response(
        patient_summary=CRITICAL_ASSESSMENT_NOTICE + ' Обсудите с врачом положительный пункт 9.',
        risks=[{'level': 'red', 'description': 'Требуется срочная оценка.', 'evidence': ['alert:3']}],
    ))
    validate_analysis_evidence(accepted, snapshot)
    # Grammar is available to the actual model, not only post-generation checks.
    assert 'pattern' in schema.model_json_schema()['properties']['patient_summary']


def test_generation_schema_is_isolated_between_patients_and_leaves_coverage_to_runtime():
    first = analysis_schema({'evidence_refs': ['diary:1'], 'active_alerts': []})
    second = analysis_schema({'evidence_refs': ['diary:9'], 'active_alerts': []})
    risk = {'level': 'yellow', 'description': 'Изменение самочувствия', 'evidence': ['diary:1']}
    assert first.model_validate(response(risks=[risk])).risks[0].evidence == ['diary:1']
    with pytest.raises(ValidationError):
        second.model_validate(response(risks=[risk]))
    assert 'pattern' not in first.model_json_schema()['properties']['patient_summary']
    snapshot = {'evidence_refs': ['alert:3'], 'active_alerts': [{'id': 3, 'level': 'red'}]}
    merely_well_formed = analysis_schema(snapshot).model_validate(response(patient_summary=CRITICAL_ASSESSMENT_NOTICE))
    with pytest.raises(ValueError):
        validate_analysis_evidence(merely_well_formed, snapshot)
