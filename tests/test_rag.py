import httpx
from fastapi import HTTPException
import pytest

from app.backend.core.config import settings
from app.backend.services.recommendations.rag_adapter import ask_existing_rag


def test_rag_disabled_requires_setup(doctor_client, patient_client, actors):
    url = f"/api/patients/{actors['patient'].id}/recommendations/generate-rag"
    assert doctor_client.post(url, json={'question': 'Учебный вопрос'}).status_code == 409
    assert patient_client.post(url, json={'question': 'Учебный вопрос'}).status_code == 403


def test_rag_adapter_and_patient_persistence(monkeypatch, doctor_client, actors):
    monkeypatch.setattr(settings, 'rag_enabled', True)
    def response(url, **kwargs):
        assert kwargs['json'] == {'question': 'Синтетический вопрос'}  # No automatic patient export.
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'answer': 'Учебный черновик [1]', 'source_ids': [1, 999],
            'sources': [{'id': 1, 'document': 'synthetic.pdf', 'page': 2}],
            'missing_information': ['Требуется экспертная проверка'], 'requires_doctor_review': True,
        })
    monkeypatch.setattr('app.backend.services.recommendations.rag_adapter.httpx.post', response)
    url = f"/api/patients/{actors['patient'].id}/recommendations/generate-rag"
    result = doctor_client.post(url, json={'question': 'Синтетический вопрос'})
    assert result.status_code == 201, result.text
    row = result.json()
    assert row['status'] == 'pending' and row['result_id'] is None
    assert row['evidence']['sources'] == [{'id': 1, 'document': 'synthetic.pdf', 'page': 2}]
    assert row['evidence']['clinical_validation'] == 'pending'
    assert doctor_client.get(f"/api/patients/{actors['patient'].id}/recommendations").json()[0]['id'] == row['id']


def test_rag_cannot_save_uncited_answer(monkeypatch):
    monkeypatch.setattr(settings, 'rag_enabled', True)
    monkeypatch.setattr('app.backend.services.recommendations.rag_adapter.httpx.post', lambda url, **kwargs: httpx.Response(
        200, request=httpx.Request('POST', url), json={'answer': 'Не подтверждено', 'source_ids': [], 'sources': [],
                                                    'missing_information': [], 'requires_doctor_review': True}))
    with pytest.raises(HTTPException) as error:
        ask_existing_rag('Тест')
    assert error.value.status_code == 409
