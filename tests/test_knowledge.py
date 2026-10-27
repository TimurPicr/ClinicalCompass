import json

import httpx
from sqlalchemy import select

from app.backend.ai.ollama import OllamaClient
from app.backend.ai.worker import process_one
from app.backend.knowledge.service import import_text, index_document, retrieve, split_text
from app.backend.knowledge.sources import sync_pubmed, sync_sources
from database.models import AIJob, Chunk, KnowledgeDocument, SourceLog
from tests.test_ai import ai_db


def knowledge_client():
    def response(request):
        payload = json.loads(request.content)
        if request.url.path == '/api/embed':
            vectors = [[1.0] + [0.0] * 1023 for _ in payload['input']]
            return httpx.Response(200, json={'embeddings': vectors})
        return httpx.Response(200, json={'message': {'content': '{"facts":[]}'}})
    return OllamaClient(transport=httpx.MockTransport(response))


def test_chunks_bounded_and_dedupe_skips_reembedding(ai_db):
    chunks = list(split_text(('Первый абзац. Второй абзац.\n' * 100)))
    assert len(chunks) > 1 and all(len(chunk) <= 1400 for chunk in chunks)
    document, created = import_text(ai_db, source='local', external_id='drug', title='Препарат',
                                    url='https://example.test/drug', category='drug_instruction', text='Сертралин: нежелательная реакция — тошнота.')
    assert created and not document.active
    same, created = import_text(ai_db, source='local', external_id='drug', title='Препарат',
                                url='https://example.test/drug', category='drug_instruction', text=document.text)
    assert same.id == document.id and not created
    ai_db.commit()
    client = knowledge_client()
    assert process_one(ai_db, client)
    assert document.active
    assert len(ai_db.scalars(select(Chunk)).all()) == 1
    assert len(ai_db.scalars(select(AIJob)).all()) == 1
    results = retrieve(ai_db, 'сертралин', client)
    assert results[0]['url'] == 'https://example.test/drug' and results[0]['document_id'] == document.id
    assert retrieve(ai_db, 'тошнота', category='drug_instruction')[0]['id'] == results[0]['id']
    assert retrieve(ai_db, 'несуществующееслово') == []
    client.close()


def test_new_version_keeps_old_active_until_indexed(ai_db):
    kwargs = dict(source='local', external_id='v', title='Документ', url='https://example.test/v', category='publication')
    old, _ = import_text(ai_db, **kwargs, text='Исходная версия')
    ai_db.commit()
    client = knowledge_client()
    process_one(ai_db, client)
    new, created = import_text(ai_db, **kwargs, text='Обновлённая версия')
    ai_db.commit()
    assert created and new.version == 2 and old.active and not new.active
    process_one(ai_db, client)
    assert new.active and not old.active
    assert ai_db.get(KnowledgeDocument, old.id).text == 'Исходная версия'
    client.close()


def test_retry_old_version_cannot_replace_newer_active_evidence(ai_db):
    kwargs = dict(source='local', external_id='retry-order', title='Документ', url='https://example.test/v', category='publication')
    old, _ = import_text(ai_db, **kwargs, text='Старая версия')
    new, _ = import_text(ai_db, **kwargs, text='Исправленная версия')
    client = knowledge_client()
    index_document(ai_db, new.id, client)
    ai_db.commit()
    index_document(ai_db, old.id, client)
    ai_db.commit()
    assert new.active and not old.active
    assert ai_db.scalar(select(SourceLog).where(SourceLog.status == 'superseded')) is not None
    client.close()


def test_clinical_context_excludes_synthetic_and_bibliographic_documents(ai_db):
    client = knowledge_client()
    for source in ['demo', 'pubmed', 'original_author']:
        document, _ = import_text(ai_db, source=source, external_id=source, title='PHQ-9',
                                  url=f'https://example.test/{source}', category='publication', text='PHQ-9: сумма баллов.',
                                  metadata={'content_type': 'bibliographic_metadata'} if source == 'pubmed' else {})
        index_document(ai_db, document.id, client)
    ai_db.commit()
    assert {item['source'] for item in retrieve(ai_db, 'PHQ-9', client)} == {'demo', 'pubmed', 'original_author'}
    clinical_context = retrieve(ai_db, 'PHQ-9', client, clinical_only=True)
    assert clinical_context and {item['source'] for item in clinical_context} == {'original_author'}
    client.close()


def test_pubmed_genuine_protocol_without_abstract_copy(ai_db):
    def respond(request):
        if request.url.path.endswith('esearch.fcgi'):
            assert request.url.params['db'] == 'pubmed'
            return httpx.Response(200, json={'esearchresult': {'idlist': ['123']}})
        assert request.url.path.endswith('efetch.fcgi')
        return httpx.Response(200, text='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Test treatment</ArticleTitle><Abstract><AbstractText>Copyright protected abstract</AbstractText></Abstract><Journal><Title>Journal</Title><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert sync_pubmed(ai_db, client) == 1
    document = ai_db.scalar(select(KnowledgeDocument))
    assert document.external_id == '123' and document.url == 'https://pubmed.ncbi.nlm.nih.gov/123/'
    assert 'Copyright protected abstract' not in document.text
    assert ai_db.scalar(select(SourceLog)).status == 'ok'


def test_sync_updates_known_older_publication_and_reports_real_denial(ai_db, monkeypatch):
    from app.backend.knowledge import sources
    monkeypatch.setattr(sources.time, 'sleep', lambda seconds: None)
    import_text(ai_db, source='pubmed', external_id='123', title='Old title',
                url='https://pubmed.ncbi.nlm.nih.gov/123/', category='publication', text='Old metadata')
    def updated(request):
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'idlist': []}})
        assert request.url.params['id'] == '123'
        return httpx.Response(200, text='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Corrected title</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
    with httpx.Client(transport=httpx.MockTransport(updated)) as client:
        assert sync_pubmed(ai_db, client) == 1
    assert [row.version for row in ai_db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.version))] == [1, 2]
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        sync_sources(ai_db, client)
    logs = ai_db.scalars(select(SourceLog)).all()
    assert any(log.source == 'grls' and log.status == 'manual_import_required' for log in logs)
    assert any(log.source == 'pubmed' and log.status == 'error' for log in logs)
