"""Reproducible integration with real local models (never used by pytest)."""
import argparse
import uuid
from sqlalchemy import select

from app.backend.ai.ollama import OllamaClient, UNTRUSTED_INSTRUCTIONS
from app.backend.ai.queue import enqueue, heavy_lock
from app.backend.ai.schemas import FactResult
from app.backend.ai.worker import process_one
from database.connection import SessionLocal
from database.models import AIJob, Patient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patient-id', type=int, help='Дополнительно выполнить полный анализ синтетического пациента')
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.patient_id:
            if not db.get(Patient, args.patient_id):
                parser.error('Пациент не найден; сначала выполните seed')
            # Index references first; do not execute unrelated patient/OCR jobs.
            knowledge_jobs = db.scalars(select(AIJob).where(AIJob.kind == 'knowledge', AIJob.status == 'pending').limit(10)).all()
            for reference_job in knowledge_jobs:
                if not process_one(db, job_id=reference_job.id):
                    raise SystemExit('Индексатор занят либо отложен; повторите позднее')
                if reference_job.status != 'completed':
                    raise SystemExit(f'Индексация {reference_job.id}: {reference_job.status}; {reference_job.error}')
            job = enqueue(db, args.patient_id, payload={'trigger': 'real-model-integration'},
                          dedupe_key='integration:' + uuid.uuid4().hex)
            db.commit()
            target_id = job.id
            process_one(db, job_id=target_id)
            target = db.get(AIJob, target_id)
            print(f'Полный анализ {target.id}: {target.status}' + (f'; {target.error}' if target.error else ''))
            if target.status != 'completed':
                raise SystemExit(1)
        else:
            with heavy_lock(db) as acquired:
                if not acquired:
                    raise SystemExit('Модель занята обработчиком. Повторите после завершения задачи.')
                client = OllamaClient()
                try:
                    vectors = client.embed(['Синтетический текст для проверки локального поиска.'])
                    result = client.structured(FactResult, UNTRUSTED_INSTRUCTIONS +
                        'Извлеки только явно написанные факты с точной цитатой.',
                        {'text': 'Это синтетический технический документ. Клинических фактов нет.'})
                    print(f'Реальные локальные модели: embedding={len(vectors[0])}; валидный JSON; фактов={len(result.facts)}')
                finally:
                    client.close()


if __name__ == '__main__':
    main()
