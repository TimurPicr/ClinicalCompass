"""Run: python -m app.backend.ai.worker [--once] [--no-sync]."""
import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app.backend.ai.ollama import OllamaClient
from app.backend.ai.queue import heavy_lock, utcnow
from app.backend.ai.service import analyze_patient
from app.backend.config import settings
from app.backend.knowledge.service import index_document
from app.backend.knowledge.sources import schedule_sync, sync_sources
from database.connection import SessionLocal
from database.models import AIJob, Document, SourceLog

logger = logging.getLogger(__name__)


def process_one(db, client=None, job_id=None):
    """One global lock covers all model loads, including embedding requests.

    Once this lock is acquired no other worker can be executing a job, so any
    persisted running job belongs to a terminated worker and is recoverable.
    """
    with heavy_lock(db) as acquired:
        if not acquired:
            return False
        for abandoned in db.scalars(select(AIJob).where(AIJob.status == 'running')):
            abandoned.status = 'pending' if abandoned.attempts < settings.ai_max_retries else 'failed'
            abandoned.error = 'Предыдущий обработчик завершился; задача восстановлена'
            abandoned.available_at = utcnow()
            abandoned.locked_at = None
            if abandoned.status == 'failed':
                abandoned.finished_at = utcnow()
                if abandoned.kind == 'document':
                    document = db.get(Document, abandoned.payload['document_id'])
                    if document and document.status != 'processed':
                        document.status = 'failed'
                        document.extraction = {**document.extraction, 'error': abandoned.error}
        db.commit()
        pending = select(AIJob).where(AIJob.status == 'pending', AIJob.available_at <= utcnow())
        if job_id is not None:  # Explicit target for the reproducible local integration CLI.
            pending = pending.where(AIJob.id == job_id)
        job = db.scalar(pending.order_by(AIJob.available_at, AIJob.id).with_for_update(skip_locked=True).limit(1))
        if not job:
            return False
        job.status, job.locked_at = 'running', utcnow()
        job.attempts += 1
        job_id = job.id
        db.commit()
        own_client = client is None
        try:
            if job.kind != 'sync':
                client = client or OllamaClient()
            if job.kind == 'analysis':
                analyze_patient(db, job.patient_id, client)
            elif job.kind == 'document':
                from app.backend.documents import process_document
                process_document(db, job.payload['document_id'], client)
            elif job.kind == 'knowledge':
                index_document(db, job.payload['document_id'], client)
            elif job.kind == 'sync':
                sync_sources(db)
            else:
                raise ValueError('Неизвестный тип AI-задачи')
            job.status, job.finished_at, job.error = 'completed', utcnow(), None
            job.locked_at = None
            db.commit()
        except Exception as exc:
            # Do not persist request/response data or raw model text in logs.
            db.rollback()
            job = db.get(AIJob, job_id)
            job.error = f'{type(exc).__name__}: обработка не завершена. Проверьте локальные модели, OCR и источник.'
            if isinstance(exc, RuntimeError) and str(exc).startswith(('Для OCR ', 'OCR не выполнен:', 'Для сканированного PDF ', 'Не удалось подготовить страницу ')):
                job.error = str(exc)  # These fixed application messages contain no clinical input.
            job.status = 'failed' if job.attempts >= settings.ai_max_retries else 'pending'
            job.available_at = utcnow() + timedelta(seconds=min(300, 10 * 2 ** (job.attempts - 1)))
            job.locked_at = None
            if job.status == 'failed':
                job.finished_at = utcnow()
                if job.kind == 'document':
                    document = db.get(Document, job.payload['document_id'])
                    if document:
                        document.status = 'failed'
                        document.extraction = {**document.extraction, 'error': job.error}
                if job.kind in {'knowledge', 'sync'}:
                    db.add(SourceLog(source='indexer', status='error', message=f'Задача {job.id}: {job.error}'))
            db.commit()
            logger.warning('AI job %s failed (%s)', job_id, type(exc).__name__)
        finally:
            if own_client and client is not None:
                client.close()
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Обработать одну доступную задачу и выйти')
    parser.add_argument('--no-sync', action='store_true', help='Не планировать синхронизацию источников')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    while True:
        with SessionLocal() as db:
            if not args.no_sync:
                schedule_sync(db)
                db.commit()
            worked = process_one(db)
        if args.once:
            break
        if not worked:
            time.sleep(2)


if __name__ == '__main__':
    main()
