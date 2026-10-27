import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select

from app.backend.ai.ollama import OllamaClient
from app.backend.ai.queue import enqueue, heavy_lock, job_view
from app.backend.auth import doctor_user
from app.backend.config import settings
from app.backend.knowledge.service import CATEGORIES, import_text, lock_identity, retrieve
from database.connection import get_db
from database.models import AIJob, KnowledgeDocument, SourceLog

router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])


@router.get('/search')
def search(q: str = Query(min_length=2, max_length=1000), category: str | None = None,
           semantic: bool = True, user=Depends(doctor_user), db=Depends(get_db)):
    if category and category not in CATEGORIES:
        raise HTTPException(422, 'Неизвестная категория')
    results, available, message = None, False, 'Поиск по тексту и метаданным'
    if semantic:
        with heavy_lock(db) as acquired:
            if acquired:
                client = None
                try:
                    client = OllamaClient()
                    results = retrieve(db, q, client, category)
                    available, message = True, 'Семантический поиск и метаданные'
                except Exception:
                    message = 'Локальные эмбеддинги недоступны; выполнен поиск по тексту и метаданным'
                finally:
                    if client:
                        client.close()
            else:
                message = 'Модель занята фоновой задачей; выполнен поиск по тексту и метаданным'
    if results is None:
        results = retrieve(db, q, category=category)
    return {'results': results, 'semantic_available': available, 'message': message}


@router.get('/sources')
def sources(user=Depends(doctor_user), db=Depends(get_db)):
    documents = db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.downloaded_at.desc()).limit(200)).all()
    logs = db.scalars(select(SourceLog).order_by(SourceLog.created_at.desc()).limit(50)).all()
    return {'documents': [{key: getattr(document, key) for key in
                           ('id', 'title', 'source', 'url', 'category', 'version', 'published_at',
                            'downloaded_at', 'active', 'external_id', 'checksum')} for document in documents],
            'logs': [{key: getattr(log, key) for key in ('id', 'source', 'status', 'message', 'created_at')} for log in logs]}


@router.post('/import', status_code=202)
async def import_document(file: UploadFile = File(...), source: str = Form('local'),
                          title: str = Form(...), url: str = Form(...),
                          category: str = Form('publication'), external_id: str = Form(''),
                          version: str = Form(''), user=Depends(doctor_user), db=Depends(get_db)):
    if category not in CATEGORIES or len(source) > 64 or not source.strip() or len(title) > 500:
        raise HTTPException(422, 'Проверьте категорию, источник и название')
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or len(url) > 2000:
        raise HTTPException(422, 'Укажите официальную HTTP(S)-ссылку на источник')
    external_id = external_id or hashlib.sha256(url.encode()).hexdigest()[:32]
    if len(external_id) > 200 or len(version) > 100:
        raise HTTPException(422, 'Слишком длинный идентификатор или версия')
    extension = Path(file.filename or '').suffix.lower()
    if extension == '.txt':
        data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, 'Файл превышает ограничение размера')
        try:
            text = data.decode('utf-8-sig')
            document, created = import_text(db, source=source, external_id=external_id, title=title,
                                            url=url, category=category, text=text,
                                            metadata={'publication_version': version, 'imported_by': user.id})
        except (UnicodeError, ValueError) as exc:
            raise HTTPException(422, str(exc))
    elif extension == '.pdf':
        from app.backend.documents import save_upload
        saved = await save_upload(file)
        lock_identity(db, source, external_id)
        existing = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source == source,
                             KnowledgeDocument.external_id == external_id, KnowledgeDocument.checksum == saved['checksum']))
        if existing:
            (Path(settings.upload_dir) / saved['storage_name']).unlink(missing_ok=True)
            return {'id': existing.id, 'status': 'indexed' if existing.active else 'queued', 'unchanged': True}
        latest = db.scalar(select(func.max(KnowledgeDocument.version)).where(
            KnowledgeDocument.source == source, KnowledgeDocument.external_id == external_id)) or 0
        document = KnowledgeDocument(source=source, external_id=external_id, title=title, url=url,
                                     category=category, text='', checksum=saved['checksum'], version=latest + 1,
                                     active=False, metadata_json={'storage_name': saved['storage_name'],
                                     'publication_version': version, 'imported_by': user.id})
        db.add(document)
        db.flush()
        enqueue(db, kind='knowledge', payload={'document_id': document.id}, dedupe_key=f'knowledge:{document.id}:{document.checksum}')
        created = True
    else:
        raise HTTPException(415, 'База знаний принимает PDF и UTF-8 TXT')
    db.commit()
    return {'id': document.id, 'status': 'queued' if not document.active else 'indexed', 'unchanged': not created}


@router.post('/sync', status_code=202)
def request_sync(user=Depends(doctor_user), db=Depends(get_db)):
    pending = db.scalar(select(AIJob).where(AIJob.kind == 'sync', AIJob.status.in_(['pending', 'running'])).limit(1))
    job = pending or enqueue(db, kind='sync', dedupe_key='manual-sync:' + uuid.uuid4().hex)
    db.commit()
    return job_view(job)
