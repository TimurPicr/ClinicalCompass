"""Run one official-source synchronization, or enqueue it for the worker."""
import argparse
import uuid

from sqlalchemy import select

from app.backend.ai.queue import enqueue
from app.backend.knowledge.sources import sync_sources
from database.connection import SessionLocal
from database.models import SourceLog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enqueue', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.enqueue:
            job = enqueue(db, kind='sync', dedupe_key='cli-sync:' + uuid.uuid4().hex)
            db.commit()
            print(f'Задача синхронизации {job.id}: {job.status}')
        else:
            sync_sources(db)
            db.commit()
            for entry in db.scalars(select(SourceLog).order_by(SourceLog.id.desc()).limit(12)):
                print(f'{entry.source}: {entry.status}: {entry.message}')


if __name__ == '__main__':
    main()
