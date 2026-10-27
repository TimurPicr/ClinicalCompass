import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.backend.ai.ollama import OllamaClient
from app.backend.ai.queue import enqueue, heavy_lock, utcnow
from app.backend.ai.schemas import AnalysisResult, validate_citations
from app.backend.ai.service import analysis_view
from app.backend.ai.worker import process_one
from database.models import AIAnalysis, AIJob, Base, Patient, User


@pytest.fixture
def ai_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(id=1, email='doctor@ai.test', name='Doctor', role='doctor', password_hash='test'),
                    User(id=2, email='patient@ai.test', name='Patient', role='patient', password_hash='test')])
        db.flush()
        db.add(Patient(id=2, doctor_id=1))
        db.commit()
        yield db
    engine.dispose()


def example_analysis(**overrides):
    return dict(summary='Доступных сведений мало', patient_summary='Продолжайте отмечать самочувствие',
                facts=[], hypotheses=[], recommendations=['Обсудить динамику на приёме'],
                changes=[], risks=[], explanation='Недостаточно наблюдений', sources=[]) | overrides


def mock_client(result=None):
    def respond(request):
        payload = json.loads(request.content)
        if request.url.path == '/api/embed':
            return httpx.Response(200, json={'embeddings': [[1.0] + [0.0] * 1023 for _ in payload['input']]})
        assert payload['stream'] is False and payload['think'] is False
        assert 'BEGIN_UNTRUSTED_DATA' in payload['messages'][1]['content']
        return httpx.Response(200, json={'message': {'content': json.dumps(result or example_analysis(), ensure_ascii=False)}})
    return OllamaClient(transport=httpx.MockTransport(respond))


def test_structured_validation_and_citation_allowlist():
    result = AnalysisResult.model_validate(example_analysis(sources=[{'id': 3, 'title': 'fake title', 'url': 'https://source.test/a', 'page': 2}]))
    assert validate_citations(result, [{'id': 3, 'title': 'Canonical', 'url': 'https://source.test/a', 'page': 2}]).sources[0].title == 'Canonical'
    with pytest.raises(ValueError):
        validate_citations(result, [])
    with pytest.raises(ValueError):
        AnalysisResult.model_validate(example_analysis(unexpected='ignored?'))


def test_embedding_rejects_fake_dimensions():
    client = OllamaClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'embeddings': [[0.1, 0.2]]})))
    with pytest.raises(ValueError, match='1024'):
        client.embed(['text'])
    client.close()


def test_queue_dedupe_and_analysis_success(ai_db):
    job = enqueue(ai_db, 2, payload={'event': 1}, dedupe_key='answer:1')
    assert enqueue(ai_db, 2, payload={'event': 1}, dedupe_key='answer:1').id == job.id
    ai_db.commit()
    client = mock_client()
    assert process_one(ai_db, client)
    assert job.status == 'completed' and job.attempts == 1
    analysis = ai_db.scalar(select(AIAnalysis))
    assert analysis.result['summary'] == 'Доступных сведений мало'
    assert 'recommendations' in analysis_view(analysis, 'doctor')['result']
    assert 'recommendations' not in analysis_view(analysis, 'patient')['result']
    assert not process_one(ai_db, client)
    client.close()


def test_queue_retry_and_terminal_error(ai_db, monkeypatch):
    from app.backend.config import settings
    monkeypatch.setattr(settings, 'ai_max_retries', 2)
    job = enqueue(ai_db, 2, dedupe_key='failing')
    ai_db.commit()
    client = OllamaClient(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert process_one(ai_db, client)
    assert job.status == 'pending' and job.attempts == 1 and 'HTTPStatusError' in job.error
    job.available_at = utcnow()
    ai_db.commit()
    assert process_one(ai_db, client)
    assert job.status == 'failed' and job.attempts == 2
    assert not ai_db.scalars(select(AIAnalysis)).all()
    client.close()


def test_crashed_job_recovered_and_global_lock_enforced(ai_db):
    job = enqueue(ai_db, 2, dedupe_key='crashed')
    job.status, job.attempts, job.locked_at = 'running', 1, utcnow()
    ai_db.commit()
    client = mock_client()
    with heavy_lock(ai_db) as acquired:
        assert acquired
        assert not process_one(ai_db, client)
    assert process_one(ai_db, client)
    assert job.status == 'completed' and job.attempts == 2
    client.close()


def test_ai_cannot_lower_red_status(ai_db):
    patient = ai_db.get(Patient, 2)
    patient.status = 'red'
    enqueue(ai_db, 2, dedupe_key='critical')
    ai_db.commit()
    client = mock_client()
    process_one(ai_db, client)
    assert patient.status == 'red'
    client.close()


def test_critical_rule_during_model_call_cannot_be_overwritten(ai_db):
    from sqlalchemy import update
    from app.backend.ai.service import analyze_patient
    ai_db.get(Patient, 2).record = {'anamnesis': 'Сохраняется тревога'}
    class ModelWithConcurrentRule:
        def embed(self, texts):
            return [[1.0] + [0.0] * 1023 for _ in texts]
        def structured(self, schema, system, data):
            assert data['patient']['deterministic_status'] == 'green'
            ai_db.execute(update(Patient).where(Patient.id == 2).values(status='red'),
                          execution_options={'synchronize_session': False})
            return AnalysisResult.model_validate(example_analysis(risks=[{'level': 'yellow', 'description': 'Предположение', 'evidence': ['confirmed_record:anamnesis']}]))
    analyze_patient(ai_db, 2, ModelWithConcurrentRule())
    ai_db.commit()
    assert ai_db.get(Patient, 2).status == 'red'


def test_private_upload_access_and_magic_validation(ai_db, tmp_path, monkeypatch):
    import io
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
    from app.backend.auth import current_user
    from app.backend.config import settings
    from app.backend.documents import router
    from database.connection import get_db
    monkeypatch.setattr(settings, 'upload_dir', tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: ai_db
    app.dependency_overrides[current_user] = lambda: ai_db.get(User, 2)
    image = io.BytesIO()
    Image.new('RGB', (10, 10), 'white').save(image, format='PNG')
    with TestClient(app) as client:
        invalid = client.post('/api/patients/2/documents', files={'file': ('fake.pdf', b'not pdf', 'application/pdf')})
        assert invalid.status_code == 415
        corrupt_png = bytearray(image.getvalue())
        marker = corrupt_png.find(b'IDAT')
        assert marker > 0
        corrupt_png[marker + 4] ^= 1  # Break image data without updating its CRC.
        assert client.post('/api/patients/2/documents', files={'file': ('bad.png', bytes(corrupt_png), 'image/png')}).status_code == 422
        uploaded = client.post('/api/patients/2/documents', files={'file': ('scan.png', image.getvalue(), 'image/png')})
        assert uploaded.status_code == 201
        document_id = uploaded.json()['id']
        assert uploaded.json()['status'] == 'pending'
        assert client.get(f'/api/documents/{document_id}/download').content == image.getvalue()
        ai_db.add(User(id=3, email='stranger@ai.test', name='Other Doctor', role='doctor', password_hash='test'))
        ai_db.commit()
        app.dependency_overrides[current_user] = lambda: ai_db.get(User, 3)
        assert client.get(f'/api/documents/{document_id}/download').status_code == 404
        assert client.get('/api/patients/2/documents').status_code == 404


def test_extraction_needs_page_provenance_and_review_does_not_overwrite(ai_db, monkeypatch):
    from app.backend import documents
    from app.backend.ai.schemas import DocumentResult
    from database.models import Document
    document = Document(patient_id=2, uploader_id=2, name='scan.png', storage_name='a'*32+'.png',
                        mime='image/png', size=1, checksum='a'*64)
    ai_db.add(document)
    ai_db.commit()
    patient = ai_db.get(Patient, 2)
    patient.record = {'diagnosis': 'Подтверждённые сведения'}
    monkeypatch.setattr(documents, 'stored_path', lambda name: name)
    monkeypatch.setattr(documents, 'extract_pages', lambda path, mime: [{'page': 1, 'text': 'Аллергия на пенициллин', 'method': 'ocr'}])
    class LocalModel:
        def structured(self, schema, system, data):
            return DocumentResult(proposals=[{'field': 'allergies', 'value': 'пенициллин', 'page': 1, 'quote': 'Аллергия на пенициллин'}])
    documents.process_document(ai_db, document.id, LocalModel())
    assert document.extraction['review_status'] == 'unconfirmed'
    documents.review_document(document.id, documents.Review(status='confirmed'), ai_db.get(User, 1), ai_db)
    assert patient.record == {'diagnosis': 'Подтверждённые сведения'}
    assert document.extraction['reviewed_by'] == 1
    class InventedQuote:
        def structured(self, schema, system, data):
            return DocumentResult(proposals=[{'field': 'diagnosis', 'value': 'Несуществующее', 'page': 2, 'quote': 'нет в тексте'}])
    documents.process_document(ai_db, document.id, InventedQuote())
    assert document.extraction['review_status'] == 'confirmed'
    assert document.extraction['proposals'][0]['value'] == 'пенициллин'
    unprocessed = Document(patient_id=2, uploader_id=2, name='new.png', storage_name='b'*32+'.png',
                           mime='image/png', size=1, checksum='b'*64)
    ai_db.add(unprocessed)
    ai_db.flush()
    with pytest.raises(ValueError, match='подтверждения'):
        documents.process_document(ai_db, unprocessed.id, InventedQuote())
