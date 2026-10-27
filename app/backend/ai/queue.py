"""Queue rows are committed with the clinical event by the caller."""
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database.models import AIJob

HEAVY_LOCK = 237478201
_sqlite_lock = Lock()  # SQLite exists only for offline unit tests.


def utcnow():
    return datetime.now(timezone.utc)


def enqueue(db, patient_id=None, kind='analysis', payload=None, dedupe_key=None):
    payload = payload or {}
    if dedupe_key is None:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        dedupe_key = f'{kind}:{patient_id}:{digest}'
    existing = db.scalar(select(AIJob).where(AIJob.dedupe_key == dedupe_key))
    if existing:
        return existing
    job = AIJob(patient_id=patient_id, kind=kind, payload=payload, dedupe_key=dedupe_key,
                status='pending', attempts=0, available_at=utcnow())
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        return db.scalar(select(AIJob).where(AIJob.dedupe_key == dedupe_key))
    return job


@contextmanager
def heavy_lock(db):
    """A transaction-scoped lock survives commits only if explicitly avoided.

    PostgreSQL session advisory lock is held on a dedicated Connection, so an
    ORM commit cannot return it to the pool. Other workers and API embedding
    requests use this same lock. Process death releases it automatically.
    """
    if db.bind.dialect.name == 'postgresql':
        with db.bind.connect() as connection:
            acquired = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': HEAVY_LOCK})
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': HEAVY_LOCK})
                    connection.commit()
    else:
        acquired = _sqlite_lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _sqlite_lock.release()


def job_view(job):
    return {key: getattr(job, key) for key in
            ('id', 'kind', 'status', 'attempts', 'error', 'created_at', 'finished_at')}
