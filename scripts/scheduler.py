"""One lightweight scheduler: time-based rules and generic Web Push reminders."""
import argparse
import logging
import time
from sqlalchemy import select, text
from app.backend.clinical import evaluate_rules
from app.backend.notifications import send_due_reminders
from database.connection import SessionLocal
from database.models import Patient

logger=logging.getLogger(__name__)

def tick(db):
    # Dedicated connection holds this lock through ORM commits and push calls.
    with db.bind.connect() as lock:
        if db.bind.dialect.name=='postgresql' and not lock.scalar(text('SELECT pg_try_advisory_lock(237478202)')):
            return
        try:
            for patient in db.scalars(select(Patient)):
                evaluate_rules(db,patient.id)
            db.commit()
            send_due_reminders(db)
        finally:
            if db.bind.dialect.name=='postgresql':
                lock.execute(text('SELECT pg_advisory_unlock(237478202)'))
                lock.commit()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with SessionLocal() as db:
                tick(db)
        except Exception as error:
            logger.warning('Scheduler failed (%s)',type(error).__name__)
        if args.once:
            return
        time.sleep(30)

if __name__=='__main__':
    main()
