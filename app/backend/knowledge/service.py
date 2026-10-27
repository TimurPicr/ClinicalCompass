import hashlib
import math
import re

from sqlalchemy import Text, func, or_, select, text as sql_text

from app.backend.ai.ollama import UNTRUSTED_INSTRUCTIONS
from app.backend.ai.queue import enqueue
from app.backend.ai.schemas import FactResult
from app.backend.config import settings
from database.models import Chunk, KnowledgeDocument, SourceLog

CATEGORIES = {'drug_instruction', 'clinical_guideline', 'publication'}


def lock_identity(db, source, external_id):
    if db.bind.dialect.name == 'postgresql':
        key = int.from_bytes(hashlib.sha256(f'knowledge:{source}:{external_id}'.encode()).digest()[:8], 'big', signed=True)
        db.execute(sql_text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def clean_text(text):
    return re.sub(r'[ \t]+', ' ', text.replace('\x00', '')).strip()


def split_text(text, size=1400, overlap=160):
    """Prefer paragraph/sentence boundaries; retain a small overlapping tail."""
    text = clean_text(text)
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n', start + size // 2, end), text.rfind('. ', start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        value = text[start:end].strip()
        if value:
            yield value
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def import_text(db, *, source, external_id, title, url, category, text, published_at=None, metadata=None, pages=None):
    if category not in CATEGORIES:
        raise ValueError('Неизвестная категория источника')
    lock_identity(db, source, external_id)
    text = clean_text(text)
    if not text:
        raise ValueError('Документ не содержит извлечённого текста')
    if len(text) > 500_000:
        raise ValueError('Максимальный объём документа — 500 000 символов')
    checksum = hashlib.sha256(text.encode()).hexdigest()
    same = db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.source == source, KnowledgeDocument.external_id == external_id,
        KnowledgeDocument.checksum == checksum,
    ).order_by(KnowledgeDocument.version.desc()))
    if same:
        return same, False
    latest = db.scalar(select(func.max(KnowledgeDocument.version)).where(
        KnowledgeDocument.source == source, KnowledgeDocument.external_id == external_id)) or 0
    info = dict(metadata or {})
    if pages:
        info['pages'] = pages
    document = KnowledgeDocument(source=source, external_id=external_id, title=title,
                                 url=url, category=category, published_at=published_at,
                                 version=latest + 1, checksum=checksum, text=text,
                                 metadata_json=info, active=False)
    db.add(document)
    db.flush()
    enqueue(db, kind='knowledge', payload={'document_id': document.id}, dedupe_key=f'knowledge:{document.id}:{checksum}')
    return document, True


def index_document(db, document_id, client):
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise ValueError('Источник не найден')
    newer_active = db.scalar(select(KnowledgeDocument).where(
        KnowledgeDocument.source == document.source, KnowledgeDocument.external_id == document.external_id,
        KnowledgeDocument.active.is_(True), KnowledgeDocument.version > document.version).limit(1))
    if newer_active:
        # An older failed job may retry after a newer version was indexed.
        # Preserve its original, but never roll active evidence back in time.
        document.active = False
        db.add(SourceLog(source=document.source, status='superseded',
                         message=f'Версия {document.version} документа {document.id} архивная: активна версия {newer_active.version}'))
        return
    existing = db.scalar(select(Chunk).where(Chunk.document_id == document.id).limit(1))
    model_changed = document.metadata_json.get('embedding_model') != settings.embedding_model
    if document.active and existing and not model_changed:
        return
    pages = document.metadata_json.get('pages')
    if not document.text and document.metadata_json.get('storage_name'):
        from app.backend.documents import extract_pages, stored_path
        pages = extract_pages(stored_path(document.metadata_json['storage_name']), 'application/pdf')
        document.text = '\n\n'.join(page['text'] for page in pages)
        document.metadata_json = {**document.metadata_json, 'pages': pages}
    pages = pages or [{'page': None, 'text': document.text}]
    pieces = [(page.get('page'), text) for page in pages for text in split_text(page['text'])]
    if len(pieces) > 500:
        raise ValueError('Слишком много фрагментов; разбейте документ на части')
    chunks = []
    for position, (page, content) in enumerate(pieces):
        # Facts are unverified annotations, never executable clinical rules.
        result = client.structured(FactResult, UNTRUSTED_INSTRUCTIONS +
                                   'Извлеки факты из фрагмента. quote должна дословно присутствовать в тексте. '
                                   'Не добавляй информации вне фрагмента.', {'text': content})
        facts = [fact.model_dump() for fact in result.facts if fact.quote in content]
        vector = client.embed([content])[0]
        chunks.append(Chunk(document_id=document.id, page=page, position=position,
                            text=content, embedding=vector, facts={'items': facts, 'verified': False}))
    # Replacement is transactional: old active versions remain searchable on failure.
    for previous in db.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.source == document.source, KnowledgeDocument.external_id == document.external_id)):
        previous.active = False
    for previous_chunk in db.scalars(select(Chunk).where(Chunk.document_id == document.id)):
        db.delete(previous_chunk)
    db.flush()
    db.add_all(chunks)
    document.active = True
    document.metadata_json = {**document.metadata_json, 'embedding_model': settings.embedding_model}
    db.add(SourceLog(source=document.source, status='indexed', message=f'Документ {document.id}, версия {document.version}, фрагментов {len(chunks)}'))


def source_view(chunk, document, score):
    return {'id': chunk.id, 'document_id': document.id, 'title': document.title,
            'url': document.url, 'source': document.source, 'category': document.category,
            'content_type': document.metadata_json.get('content_type', 'imported_text'),
            'page': chunk.page, 'text': chunk.text, 'score': round(float(score), 6)}


def retrieve(db, query, client=None, category=None, limit=6, max_chars=6500, clinical_only=False):
    """Metadata search always works; semantic ranking requires real embeddings."""
    limit = min(max(int(limit), 1), 8)
    base = select(Chunk, KnowledgeDocument).join(KnowledgeDocument).where(KnowledgeDocument.active.is_(True))
    if category:
        base = base.where(KnowledgeDocument.category == category)
    if clinical_only:
        content_type = KnowledgeDocument.metadata_json['content_type'].as_string()
        base = base.where(KnowledgeDocument.source != 'demo',
                          or_(content_type.is_(None), content_type != 'bibliographic_metadata'))
    tokens = [token for token in re.findall(r'[\w-]+', query.lower()) if len(token) > 2][:16]
    vector = client.embed(['Instruct: Retrieve relevant medical evidence for the query.\nQuery: ' + query])[0] if client else None
    if vector and db.bind.dialect.name == 'postgresql':
        distance = Chunk.embedding.cosine_distance(vector)
        candidates = db.execute(base.where(Chunk.embedding.is_not(None)).order_by(distance).limit(40)).all()
    else:
        # Only tests use SQLite. Production nearest-neighbour search runs in PostgreSQL.
        if tokens and not vector:
            filters = [or_(Chunk.text.ilike(f'%{token}%'), KnowledgeDocument.title.ilike(f'%{token}%'),
                           KnowledgeDocument.metadata_json.cast(Text).ilike(f'%{token}%')) for token in tokens]
            base = base.where(or_(*filters))
        candidates = db.execute(base.limit(200)).all()
    ranked = []
    for chunk, document in candidates:
        haystack = f'{document.title} {document.metadata_json} {chunk.text}'.lower()
        lexical = sum(token in haystack for token in tokens) / max(1, len(tokens))
        semantic = 0.0
        if vector is not None and chunk.embedding is not None:
            embedded = list(chunk.embedding)
            denominator = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in embedded))
            semantic = sum(x*y for x, y in zip(vector, embedded)) / denominator if denominator else 0
        score = semantic * 0.8 + lexical * 0.2 if vector is not None else lexical
        ranked.append((score, chunk, document))
    ranked.sort(key=lambda item: item[0], reverse=True)
    result, remaining = [], max_chars
    for score, chunk, document in ranked[:limit]:
        if len(chunk.text) > remaining:
            continue
        result.append(source_view(chunk, document, score))
        remaining -= len(chunk.text)
    return result
