"""PostgreSQL-specific serialization and migration checks, opt-in via TEST_DATABASE_URL."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.backend.models.clinical import Alert, DeliveryAttempt, TreatmentPlan
from app.backend.models.user import User
from app.backend.services.workflows import create_alert

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Requires isolated PostgreSQL TEST_DATABASE_URL')


def test_postgres_serializes_duplicate_alerts(db_factory, actors):
    patient_id = actors['patient'].id
    def submit():
        with db_factory() as db:
            patient = db.scalar(select(User).where(User.id == patient_id).with_for_update())
            alert = create_alert(db, patient, 'urgent_help_requested', 'concurrent-urgent', 'Synthetic request', 'critical')
            db.commit()
            return alert.id
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: submit(), range(4)))
    assert len(set(ids)) == 1
    with db_factory() as db:
        assert db.scalar(select(func.count()).select_from(Alert)) == 1
        assert db.scalar(select(func.count()).select_from(DeliveryAttempt)) == 1


def test_postgres_migration_roundtrip_and_drift(db_factory):
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.check(cfg)
    command.downgrade(cfg, 'base')
    command.upgrade(cfg, 'head')
    command.check(cfg)


def test_postgres_plan_versions_use_patient_lock(db_factory, actors):
    patient_id = actors['patient'].id
    doctor_id = actors['doctor'].id
    def create_version():
        with db_factory() as db:
            db.scalar(select(User).where(User.id == patient_id).with_for_update())
            version = (db.scalar(select(func.max(TreatmentPlan.version)).where(TreatmentPlan.patient_id == patient_id)) or 0) + 1
            plan = TreatmentPlan(patient_id=patient_id, doctor_id=doctor_id, version=version, title='Synthetic plan', instructions='Test only')
            db.add(plan)
            db.commit()
            return version
    with ThreadPoolExecutor(max_workers=3) as pool:
        versions = list(pool.map(lambda _: create_version(), range(3)))
    assert sorted(versions) == [1, 2, 3]
