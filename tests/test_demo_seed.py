"""The demo must be internally consistent before it is used for an AI evaluation."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
import pytest
from sqlalchemy import func, select

from app.backend.clinical_common import aware
from app.backend.config import settings
from app.backend.monitoring import evaluate_rules
from app.backend.questionnaires import validate_answers
from database.models import (AIAnalysis, AIJob, Alert, Assignment, Audit, Diary, Document,
                             Intake, Message, Patient, Prescription, PrescriptionVersion,
                             Response, User)
from scripts import seed_demo
from scripts.demo_cases import CASES

NOW = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)  # 05:00 Moscow, before today's doses/diary.
ZONE = ZoneInfo('Europe/Moscow')


@pytest.fixture
def demo(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'upload_dir', tmp_path)
    monkeypatch.setattr(settings, 'demo_rules', False)
    doctor = seed_demo.seed(db, now=NOW)
    return doctor, {case['key']: db.scalar(select(User).where(User.email == f'{case["key"]}@example.com')) for case in CASES}


def rows(db, model, patient_id):
    return list(db.scalars(select(model).where(model.patient_id == patient_id)))


def test_card_diary_questionnaires_and_alerts_agree(db, demo):
    doctor, users = demo
    expected = {'anna': ('green', [14, 8, 5], [5, 4, 3]),
                'pavel': ('yellow', [7, 8, 7], [15, 13, 16]),
                'maria': ('red', [19, 21, 24], [10, 11, 12]),
                'andrey': ('yellow', [5, 6, 6], [16, 17, 18])}
    for key, user in users.items():
        patient = db.get(Patient, user.id)
        assert patient.doctor_id == doctor.id
        assert patient.status == expected[key][0]
        assert patient.record['diagnosis_code'] in {'F32.1', 'F32.2', 'F41.1'}
        assert 'СИНТЕТИЧЕСКИЙ' in patient.record['notes']
        assert patient.record != patient.reported_record
        diary = sorted(rows(db, Diary, user.id), key=lambda row: aware(row.created_at))
        assert len(diary) == 21
        assert len({row.comment for row in diary}) == 21
        assert not any('[DEMO_CRITICAL]' in row.comment for row in diary)
        if key == 'anna':
            assert diary[-1].mood > diary[0].mood and diary[-1].anxiety < diary[0].anxiety
        if key == 'maria':
            assert diary[-1].mood < diary[0].mood and diary[-1].anxiety > diary[0].anxiety
        grouped = {'phq9': [], 'gad7': []}
        for response in sorted(rows(db, Response, user.id), key=lambda row: aware(row.created_at)):
            assignment = db.get(Assignment, response.assignment_id)
            assert not assignment.active
            assert assignment.patient_id == user.id
            assert validate_answers(assignment.snapshot, response.answers) == response.score
            grouped[assignment.snapshot['kind']].append(response.score)
            if assignment.snapshot['kind'] == 'phq9':
                assert (response.answers['q9'] > 0) == (key == 'maria' and response.score == 24)
        assert grouped == {'phq9': expected[key][1], 'gad7': expected[key][2]}
        active = [row for row in rows(db, Alert, user.id) if row.state not in {'dismissed', 'resolved'}]
        assert not any(row.category == 'demo_critical' for row in active)
        assert any(row.category == 'self_harm_screen' for row in active) == (key == 'maria')
        assert any(row.category == 'side_effect' for row in active) == (key == 'pavel')
        assert any(row.category == 'adherence' for row in active) == (key == 'pavel')
        assert not any(row.category.startswith('missing_') for row in active)
        evaluate_rules(db, user.id, now=NOW)
        assert patient.status == expected[key][0]


def test_historical_medication_versions_schedule_and_reports_match(db, demo):
    _, users = demo
    for key in ('anna', 'pavel', 'maria'):
        patient_id = users[key].id
        prescription = db.scalar(select(Prescription).where(Prescription.patient_id == patient_id))
        versions = list(db.scalars(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription.id)))
        assert prescription.current_version == len(versions)
        intakes = sorted(rows(db, Intake, patient_id), key=lambda row: aware(row.scheduled_at))
        assert len(intakes) == 21
        for intake in intakes:
            applicable = max((version for version in versions if aware(version.created_at) <= aware(intake.scheduled_at)),
                             key=lambda version: version.version)
            assert intake.version == applicable.version
            local = aware(intake.scheduled_at).astimezone(ZONE)
            assert local.strftime('%H:%M') in applicable.data['times']
            assert local.date().isoformat() >= applicable.data['start_date']
            assert local.second == local.microsecond == 0
            assert bool(intake.reason) == (intake.status == 'skipped')
            assert (intake.actual_at is None) == (intake.status == 'skipped')
            if intake.status == 'taken':
                assert aware(intake.actual_at) >= aware(intake.scheduled_at)
        assert {row.version for row in intakes} == {row.version for row in versions}
        assert sum(row.status == 'skipped' for row in intakes) == (2 if key == 'pavel' else 0)
        assert sum(bool(row.side_effect) for row in intakes) == (1 if key == 'pavel' else 0)
        if key == 'pavel':
            report = next(row for row in intakes if row.side_effect)
            diary = next(row for row in rows(db, Diary, patient_id)
                         if aware(row.created_at).astimezone(ZONE).date() == aware(report.scheduled_at).astimezone(ZONE).date())
            assert 'тошнил' in diary.comment


def test_andrey_is_an_unmedicated_prescribing_consultation_not_an_ai_order(db, demo):
    _, users = demo
    user = users['andrey']
    patient = db.get(Patient, user.id)
    assert patient.birth_date < NOW.date().replace(year=NOW.year - 18)
    assert patient.record['diagnosis_code'] == 'F41.1'
    assert 'восьми месяцев' in patient.record['anamnesis']
    assert 'Авиандра' in patient.record['treatment_history']
    assert 'не обязательный выбор' in patient.record['treatment_history']
    assert 'Препарат ещё не назначен' in patient.record['treatment_history']
    assert 'СКФ 104' in patient.record['examinations']
    assert not rows(db, Prescription, user.id)
    assert not rows(db, Intake, user.id)
    assert not rows(db, AIAnalysis, user.id)


def test_no_future_observations_even_before_morning_schedule(db, demo, tmp_path):
    for model in (Diary, Response, Document, Message):
        assert all(aware(row.created_at) <= NOW for row in db.scalars(select(model)))
    for row in db.scalars(select(Intake)):
        assert aware(row.scheduled_at) <= NOW
        assert not row.actual_at or aware(row.actual_at) <= NOW
    for row in db.scalars(select(Assignment).where(Assignment.active.is_(True))):
        assert aware(row.due_at) > NOW
        assert aware(row.due_at).astimezone(ZONE).strftime('%H:%M') == '20:00'
    for document in db.scalars(select(Document)):
        path = tmp_path / document.storage_name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == document.checksum
        with Image.open(path) as image:
            image.verify()
        assert document.status == 'pending'
        assert document.extraction == {}
    assert db.scalar(select(func.count()).select_from(AIAnalysis)) == 0
    assert db.scalar(select(func.count()).select_from(AIJob).where(AIJob.kind == 'analysis')) == 4
    assert db.scalar(select(func.count()).select_from(AIJob).where(AIJob.kind == 'document')) == 4


def _counts(db):
    return {model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in (User, Patient, Diary, Assignment, Response, Prescription,
                          PrescriptionVersion, Intake, Message, Document, AIAnalysis, AIJob, Alert, Audit)}


def test_default_seed_is_idempotent_and_preserves_clinician_edits(db, demo, tmp_path):
    doctor, users = demo
    user = users['anna']
    patient = db.get(Patient, user.id)
    patient.record = {**patient.record, 'allergies': 'Уточнение лечащего врача'}
    patient.reported_record = {'anamnesis': 'Новая запись пациента'}
    user.name = 'Имя, изменённое пользователем'
    user.password_hash = 'preserved-hash'
    db.commit()
    before = _counts(db)
    before_files = set(tmp_path.iterdir())
    assert seed_demo.seed(db, now=NOW + timedelta(days=2)).id == doctor.id
    assert _counts(db) == before
    assert set(tmp_path.iterdir()) == before_files
    assert patient.record['allergies'] == 'Уточнение лечащего врача'
    assert patient.reported_record == {'anamnesis': 'Новая запись пациента'}
    assert user.name == 'Имя, изменённое пользователем'
    assert user.password_hash == 'preserved-hash'


def test_named_cohort_has_separate_doctor_and_preserves_old_accounts(db, demo, tmp_path):
    doctor, users = demo
    original_ids = {key: user.id for key, user in users.items()}
    original_records = {user.id: dict(db.get(Patient, user.id).record) for user in users.values()}
    cohort_doctor = seed_demo.seed(db, now=NOW, cohort='realistic-v2')
    assert cohort_doctor.id != doctor.id
    assert cohort_doctor.email == 'doctor.realistic-v2@example.com'
    cohort_patients = list(db.scalars(select(Patient).where(Patient.doctor_id == cohort_doctor.id)))
    assert len(cohort_patients) == 4
    assert not set(original_ids.values()) & {row.id for row in cohort_patients}
    for case in CASES:
        user = db.scalar(select(User).where(User.email == f'{case["key"]}.realistic-v2@example.com'))
        assert user.name == case['name']
        assert db.get(Patient, user.id).doctor_id == cohort_doctor.id
        assert db.get(Patient, original_ids[case['key']]).record == original_records[original_ids[case['key']]]
    before = _counts(db)
    files = set(tmp_path.iterdir())
    seed_demo.seed(db, now=NOW, cohort='realistic-v2')
    assert _counts(db) == before
    assert set(tmp_path.iterdir()) == files


def test_existing_patient_email_is_not_claimed_or_rewritten(db, doctor, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'upload_dir', tmp_path)
    stranger = User(email='anna@example.com', name='Другой человек', role='patient', password_hash='private-hash')
    db.add(stranger)
    db.flush()
    profile = Patient(id=stranger.id, doctor_id=doctor.id, record={'diagnosis': 'Существующая карта'})
    db.add(profile)
    db.commit()
    seed_demo.seed(db, now=NOW)
    assert stranger.name == 'Другой человек' and stranger.password_hash == 'private-hash'
    assert profile.record == {'diagnosis': 'Существующая карта'}
    assert not rows(db, Diary, stranger.id)
    assert not rows(db, Prescription, stranger.id)
    assert not rows(db, Document, stranger.id)


@pytest.mark.parametrize('cohort', ['', '../old', 'Other', 'a@b', 'x' * 33])
def test_invalid_cohort_has_no_side_effects(db, tmp_path, monkeypatch, cohort):
    monkeypatch.setattr(settings, 'upload_dir', tmp_path)
    with pytest.raises(ValueError, match='Cohort'):
        seed_demo.seed(db, now=NOW, cohort=cohort)
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert not list(tmp_path.iterdir())
