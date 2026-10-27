"""Domain invariants, snapshots, authorization, transactions and risk evidence."""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
import pytest
from sqlalchemy import select, func
from app.backend.clinical import (aware, ensure_standard_templates, evaluate_rules,
                                  record_event, next_due)
from app.backend.questionnaires import standard_schema, validate_answers, validate_schema
from database.models import (AIJob, Alert, AlertAction, Assignment, Audit, Diary, Intake,
                             Patient, Prescription, PrescriptionVersion,
                             QuestionnaireTemplate, Response, utcnow)
from tests.conftest import sign_in


def assign(db, patient, kind='phq9', schedule=None):
    ensure_standard_templates(db)
    template = db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.kind == kind))
    row = Assignment(patient_id=patient.id, template_id=template.id,
                     snapshot={'name': template.name, 'kind': kind, 'version': 1, 'schema': template.schema},
                     due_at=utcnow() - timedelta(hours=1), schedule=schedule or {'frequency': 'once'})
    db.add(row)
    db.commit()
    return row


def prescription(db, doctor, patient, *, start=None):
    start = start or utcnow() - timedelta(days=8)
    row = Prescription(patient_id=patient.id, doctor_id=doctor.id, current_version=1)
    db.add(row)
    db.flush()
    db.add(PrescriptionVersion(prescription_id=row.id, version=1, created_at=start,
                              data={'name': 'Синтетический препарат', 'substance': '', 'dose': '10', 'unit': 'мг',
                                    'times': ['09:00', '20:00'], 'start_date': start.date().isoformat(), 'end_date': None, 'comment': 'Тест'}))
    db.commit()
    return row


def test_record_separates_reports_audits_and_permissions(doctor_client, db, doctor, patient, other_doctor):
    response = doctor_client.put(f'/api/patients/{patient.id}/record', json={'data': {'diagnosis': 'Условный диагноз', 'diagnosis_code': 'F32.1', 'allergies': 'Проверено'}, 'birth_date': '1990-01-01'})
    assert response.status_code == 200, response.text
    assert response.json()['confirmed']['diagnosis_code'] == 'F32.1'
    sign_in(doctor_client, patient.email)
    response = doctor_client.put(f'/api/patients/{patient.id}/record', json={'data': {'allergies': 'Со слов пациента'}})
    assert response.status_code == 200
    assert response.json()['confirmed']['allergies'] == 'Проверено'
    assert response.json()['reported']['allergies'] == 'Со слов пациента'
    assert doctor_client.put(f'/api/patients/{patient.id}/record', json={'data': {'diagnosis': 'Своя формулировка'}}).status_code == 403
    assert db.scalar(select(func.count()).select_from(Audit).where(Audit.patient_id == patient.id)) == 2
    assert db.scalar(select(AIJob).where(AIJob.patient_id == patient.id)).status == 'pending'
    sign_in(doctor_client, other_doctor.email)
    assert doctor_client.get(f'/api/patients/{patient.id}/record').status_code == 404
    assert doctor_client.get('/api/patients').json() == []


def test_questionnaire_assignment_score_idempotency_and_critical(patient_client, db, patient):
    assignment = assign(db, patient)
    answers = {f'q{i}': 2 for i in range(1, 10)}
    payload = {'answers': answers, 'idempotency_key': 'submission-1'}
    response = patient_client.post(f'/api/assignments/{assignment.id}/responses', json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['score'] == 18
    assert response.json()['severity_label'] == 'Умеренно тяжёлая'
    assert db.get(Patient, patient.id).status == 'red'
    alerts = list(db.scalars(select(Alert).where(Alert.patient_id == patient.id)))
    assert any(a.category == 'self_harm_screen' and a.source_url.startswith('https://www.phqscreeners.com/') for a in alerts)
    assert patient_client.post(f'/api/assignments/{assignment.id}/responses', json=payload).json()['id'] == response.json()['id']
    assert db.scalar(select(func.count()).select_from(Response)) == 1
    assert db.scalar(select(func.count()).select_from(AIJob)) == 1
    assert patient_client.post(f'/api/assignments/{assignment.id}/responses', json={'answers': answers}).status_code == 409


def test_invalid_responses_do_not_save_or_queue(patient_client, db, patient):
    assignment = assign(db, patient, 'gad7')
    for answers in [{'q1': 1}, {f'q{i}': 4 for i in range(1, 8)}, {f'q{i}': True for i in range(1, 8)}]:
        assert patient_client.post(f'/api/assignments/{assignment.id}/responses', json={'answers': answers}).status_code == 422
    assert db.scalar(select(func.count()).select_from(Response)) == 0
    assert db.scalar(select(func.count()).select_from(AIJob)) == 0


def test_detailed_alerts_are_only_for_attached_doctor(patient_client, db, patient, doctor, other_doctor):
    alert = Alert(patient_id=patient.id, level='yellow', category='physician_review',
                  reason='Синтетическое обоснование для врача', source='ai',
                  fingerprint=f'private-test:{patient.id}', comment='Синтетическое врачебное решение')
    db.add(alert)
    db.commit()
    path = f'/api/patients/{patient.id}/alerts'
    assert patient_client.get(path).status_code == 403
    # Status and the patient-facing summary retain their separate access paths.
    assert patient_client.get(f'/api/patients/{patient.id}').status_code == 200
    sign_in(patient_client, other_doctor.email)
    assert patient_client.get(path).status_code == 404
    sign_in(patient_client, doctor.email)
    response = patient_client.get(path)
    assert response.status_code == 200
    assert response.json()[0]['comment'] == 'Синтетическое врачебное решение'


def test_assignment_snapshot_survives_template_edits(doctor_client, db, patient):
    original = {'questions': [{'id': 'well', 'label': 'Как самочувствие?', 'type': 'number', 'min': 0, 'max': 10}]}
    created = doctor_client.post('/api/templates', json={'name': 'Контроль', 'schema': original})
    assert created.status_code == 201, created.text
    assigned = doctor_client.post(f'/api/patients/{patient.id}/assignments', json={'template_id': created.json()['id'], 'due_at': utcnow().isoformat(), 'schedule': {'frequency': 'once'}})
    assert assigned.status_code == 201, assigned.text
    changed = {'questions': [{'id': 'new', 'label': 'Другой вопрос', 'type': 'text'}]}
    assert doctor_client.put(f'/api/templates/{created.json()["id"]}', json={'name': 'Контроль 2', 'schema': changed}).json()['version'] == 2
    assert doctor_client.get(f'/api/patients/{patient.id}/assignments').json()[0]['snapshot']['schema'] == original
    sign_in(doctor_client, patient.email)
    assert doctor_client.post(f'/api/assignments/{assigned.json()["id"]}/responses', json={'answers': {'well': 8}}).status_code == 201


def test_custom_question_types_and_invalid_schema():
    schema = {'questions': [
        {'id': 'single', 'label': 'Один', 'type': 'single', 'options': [{'value': 'yes', 'label': 'Да'}, {'value': 'no', 'label': 'Нет'}]},
        {'id': 'multi', 'label': 'Несколько', 'type': 'multiple', 'options': [{'value': 'a', 'label': 'А'}, {'value': 'b', 'label': 'Б'}]},
        {'id': 'number', 'label': 'Число', 'type': 'number', 'min': 1, 'max': 7},
        {'id': 'text', 'label': 'Текст', 'type': 'text'},
    ]}
    validate_schema(schema)
    snapshot = {'kind': 'custom', 'schema': schema}
    assert validate_answers(snapshot, {'single': 'yes', 'multi': ['a', 'b'], 'number': 5, 'text': 'Комментарий'}) is None
    with pytest.raises(HTTPException):
        validate_answers(snapshot, {'single': 'yes', 'multi': ['a', 'a'], 'number': 5, 'text': ''})
    with pytest.raises(HTTPException):
        validate_schema({'questions': [{'id': 'same', 'label': 'x', 'type': 'text'}, {'id': 'same', 'label': 'x', 'type': 'text'}]})


def test_prescription_version_history_and_permissions(doctor_client, db, doctor, patient):
    values = {'name': 'Препарат', 'dose': '10', 'unit': 'мг', 'times': ['09:00'], 'start_date': utcnow().date().isoformat(), 'comment': 'Тест'}
    response = doctor_client.post(f'/api/patients/{patient.id}/prescriptions', json=values)
    assert response.status_code == 201, response.text
    changed = doctor_client.put(f'/api/prescriptions/{response.json()["id"]}', json={**values, 'dose': '20', 'times': ['20:00']})
    assert changed.status_code == 200, changed.text
    assert [v['data']['dose'] for v in changed.json()['versions']] == ['10', '20']
    assert changed.json()['current_version'] == 2
    sign_in(doctor_client, patient.email)
    assert doctor_client.put(f'/api/prescriptions/{response.json()["id"]}', json=values).status_code == 403
    assert len(doctor_client.get(f'/api/patients/{patient.id}/prescriptions').json()[0]['versions']) == 2


def test_intake_historical_version_side_effect_and_duplicate(patient_client, db, doctor, patient):
    row = prescription(db, doctor, patient)
    scheduled = (utcnow() - timedelta(days=2)).astimezone(__import__('zoneinfo').ZoneInfo('Europe/Moscow')).replace(hour=9, minute=0, second=0, microsecond=0)
    db.add(PrescriptionVersion(prescription_id=row.id, version=2, created_at=utcnow() - timedelta(days=1), data={**db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == row.id)).data, 'dose': '20', 'times': ['20:00']}))
    row.current_version = 2
    db.commit()
    payload = {'scheduled_at': scheduled.isoformat(), 'actual_at': (scheduled + timedelta(minutes=12)).isoformat(), 'status': 'taken', 'side_effect': 'Тошнота', 'severity': 4}
    response = patient_client.post(f'/api/prescriptions/{row.id}/intakes', json=payload)
    assert response.status_code == 201, response.text
    assert response.json()['version'] == 1
    assert patient_client.post(f'/api/prescriptions/{row.id}/intakes', json=payload).status_code == 409
    assert db.get(Patient, patient.id).status == 'yellow'
    assert db.scalar(select(Alert).where(Alert.category == 'side_effect')).reason.endswith('не установлена.')


def test_diary_directions_bounds_queue_and_demo(patient_client, db, patient, monkeypatch):
    from app.backend.config import settings
    monkeypatch.setattr(settings, 'demo_rules', True)
    values = {'mood': 7, 'anxiety': 2, 'sleep': 6, 'energy': 8, 'wellbeing': 7, 'comment': 'Синтетическая запись'}
    response = patient_client.post(f'/api/patients/{patient.id}/diary', json=values)
    assert response.status_code == 201, response.text
    assert db.get(Patient, patient.id).status == 'green'
    assert patient_client.post(f'/api/patients/{patient.id}/diary', json={**values, 'mood': 11}).status_code == 422
    response = patient_client.post(f'/api/patients/{patient.id}/diary', json={**values, 'comment': '[DEMO_CRITICAL]'})
    assert response.status_code == 201
    assert db.get(Patient, patient.id).status == 'red'
    assert db.scalar(select(func.count()).select_from(AIJob)) == 2
    monkeypatch.setattr(settings, 'demo_rules', False)
    evaluate_rules(db, patient.id)
    assert db.get(Patient, patient.id).status == 'green'


def test_operational_rules_feedback_and_no_critical_downgrade(doctor_client, db, patient, doctor):
    assignment = assign(db, patient)
    db.add(Response(patient_id=patient.id, assignment_id=assignment.id, answers={f'q{i}': 1 for i in range(1, 10)}, score=9))
    db.add(Diary(patient_id=patient.id, mood=8, anxiety=2, sleep=7, energy=7, wellbeing=8))
    db.flush()
    evaluate_rules(db, patient.id)
    db.commit()
    critical = db.scalar(select(Alert).where(Alert.category == 'self_harm_screen'))
    assert critical is not None
    # A later low score and a green AI result cannot clear an unreviewed finding.
    db.add(Response(patient_id=patient.id, assignment_id=assignment.id, answers={f'q{i}': 0 for i in range(1, 10)}, score=0))
    db.flush()
    evaluate_rules(db, patient.id)
    assert db.get(Patient, patient.id).status == 'red'
    result = doctor_client.post(f'/api/alerts/{critical.id}/actions', json={'action': 'dismissed', 'comment': 'Проведена очная оценка; основание сохранено'})
    assert result.status_code == 200, result.text
    assert len(result.json()['actions']) == 1
    assert db.get(Patient, patient.id).status == 'green'
    assert db.scalar(select(AlertAction)).actor_id == doctor.id


def test_rule_dedupe_queue_and_missing_data(db, patient):
    row = db.get(Patient, patient.id)
    row.monitoring_started_at = utcnow() - timedelta(days=4)
    db.commit()
    record_event(db, patient.id, 'same-event')
    record_event(db, patient.id, 'same-event')
    db.commit()
    assert db.scalar(select(func.count()).select_from(AIJob)) == 1
    assert db.scalar(select(func.count()).select_from(Alert)) == 1
    assert row.status == 'yellow'
    db.add(Diary(patient_id=patient.id, mood=8, anxiety=2, sleep=8, energy=8, wellbeing=8))
    db.flush()
    evaluate_rules(db, patient.id)
    assert row.status == 'green'
    assert db.scalar(select(Alert)).state == 'resolved'


def test_recurring_schedule_rejects_double_cycle(patient_client, db, patient):
    assignment = assign(db, patient, 'gad7', {'frequency': 'daily'})
    payload = {'answers': {f'q{i}': 0 for i in range(1, 8)}}
    assert patient_client.post(f'/api/assignments/{assignment.id}/responses', json=payload).status_code == 201
    assert aware(assignment.due_at) > utcnow()
    assert patient_client.post(f'/api/assignments/{assignment.id}/responses', json=payload).status_code == 409


def test_recurrence_preserves_local_time_across_dst():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Europe/Berlin')
    assignment = Assignment(due_at=datetime(2026, 10, 24, 7, tzinfo=timezone.utc), schedule={'frequency': 'daily'})
    result = next_due(assignment, datetime(2026, 10, 24, 12, tzinfo=timezone.utc), zone)
    assert result.astimezone(zone).hour == 9
    assert result.hour == 8  # DST ends October 25.


@pytest.mark.parametrize('kind,count', [('phq9', 9), ('gad7', 7)])
def test_standard_scoring_full_range_and_fixed_schema(kind, count):
    schema = standard_schema(kind)
    assert len(schema['questions']) == count
    assert len(schema['sources']) == 2
    for value in range(4):
        assert validate_answers({'kind': kind, 'schema': schema}, {f'q{i}': value for i in range(1, count + 1)}) == value * count


def test_locked_record_refresh_preserves_a_write_missing_from_identity_map(doctor_client, db, patient):
    from sqlalchemy import update
    cached = db.get(Patient, patient.id)
    assert cached.record == {}
    # Simulate a writer that committed while this request waited for its lock.
    # Synchronize_session=False deliberately leaves the ORM identity map stale.
    db.execute(update(Patient).where(Patient.id == patient.id).values(record={'allergies': 'Новая подтверждённая аллергия'})
               .execution_options(synchronize_session=False))
    db.commit()
    assert cached.record == {}
    response = doctor_client.put(f'/api/patients/{patient.id}/record', json={'data': {'notes': 'Дополнение'}})
    assert response.status_code == 200, response.text
    assert response.json()['confirmed'] == {'allergies': 'Новая подтверждённая аллергия', 'notes': 'Дополнение'}


def test_locked_assignment_refresh_rejects_already_completed_submission(patient_client, db, patient):
    from sqlalchemy import update
    assignment = assign(db, patient)
    assert assignment.active is True
    db.execute(update(Assignment).where(Assignment.id == assignment.id).values(active=False)
               .execution_options(synchronize_session=False))
    db.commit()
    assert assignment.active is True
    response = patient_client.post(f'/api/assignments/{assignment.id}/responses',
                                   json={'answers': {f'q{i}': 0 for i in range(1, 10)}, 'idempotency_key': 'new-concurrent-key'})
    assert response.status_code == 409, response.text
    assert db.scalar(select(func.count()).select_from(Response)) == 0


def test_locked_prescription_refresh_preserves_current_version(doctor_client, db, doctor, patient):
    from sqlalchemy import update
    row = prescription(db, doctor, patient)
    previous = db.scalar(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == row.id))
    db.add(PrescriptionVersion(prescription_id=row.id, version=2, data={**previous.data, 'dose': '20'}))
    db.execute(update(Prescription).where(Prescription.id == row.id).values(current_version=2)
               .execution_options(synchronize_session=False))
    db.commit()
    assert row.current_version == 1
    response = doctor_client.put(f'/api/prescriptions/{row.id}', json={**previous.data, 'dose': '30'})
    assert response.status_code == 200, response.text
    assert response.json()['current_version'] == 3
    assert [v['data']['dose'] for v in response.json()['versions']] == ['10', '20', '30']


def test_locked_intake_refresh_rejects_stopped_prescription(patient_client, db, doctor, patient):
    from sqlalchemy import update
    from zoneinfo import ZoneInfo
    row = prescription(db, doctor, patient)
    db.execute(update(Prescription).where(Prescription.id == row.id).values(active=False)
               .execution_options(synchronize_session=False))
    db.commit()
    assert row.active is True
    scheduled = (utcnow() - timedelta(days=2)).astimezone(ZoneInfo('Europe/Moscow')).replace(hour=9, minute=0, second=0, microsecond=0)
    response = patient_client.post(f'/api/prescriptions/{row.id}/intakes', json={'scheduled_at': scheduled.isoformat(), 'status': 'taken'})
    assert response.status_code == 409, response.text
    assert db.scalar(select(func.count()).select_from(Intake)) == 0
