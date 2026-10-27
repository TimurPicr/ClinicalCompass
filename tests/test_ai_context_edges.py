"""Context overflow, corrupt cross-patient links and durable AI risk lifecycle."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.backend import monitoring
from app.backend.ai import service
from app.backend.ai.schemas import AnalysisResult, CRITICAL_ASSESSMENT_NOTICE
from app.backend.questionnaire_routes import ensure_standard_templates
from database.models import (AIAnalysis, Alert, Assignment, Diary, Intake, Patient, Prescription,
                             PrescriptionVersion, QuestionnaireTemplate, Response, User)


@pytest.fixture
def edge_clock(db, patient, monkeypatch):
    now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utcnow', lambda: now)
    monkeypatch.setattr(monitoring, 'utcnow', lambda: now)
    monkeypatch.setattr(service, 'retrieve', lambda *args, **kwargs: [])
    db.get(Patient, patient.id).monitoring_started_at = now - timedelta(hours=1)
    db.flush()
    return now


def rule_alert(db, patient, now, index):
    row = Alert(patient_id=patient.id, level='red', category='self_harm_screen',
                reason='Синтетический положительный пункт 9: требуется оценка врача.',
                source='rule:phq9-item9', fingerprint=f'{patient.id}:synthetic-q9:{index}',
                created_at=now - timedelta(minutes=index + 1))
    db.add(row)
    db.flush()
    return row


class EvidenceModel:
    def __init__(self, risks, patient_summary=None):
        self.risks = risks
        self.patient_summary = patient_summary

    def structured(self, schema, system, data):
        summary = self.patient_summary
        if summary is None:
            critical = any(alert['level'] == 'red' for alert in data['patient']['active_alerts'])
            summary = (CRITICAL_ASSESSMENT_NOTICE + ' ' if critical else '') + 'Данные переданы врачу.'
        return AnalysisResult(summary='Синтетическое наблюдение.', patient_summary=summary,
                              facts=[], hypotheses=[], recommendations=[], changes=[],
                              risks=self.risks, explanation='Оценка ограничена переданными событиями.', sources=[])


def test_more_than_twenty_critical_rules_fails_explicitly_instead_of_silently_hiding_one(db, patient, edge_clock):
    for index in range(21):
        rule_alert(db, patient, edge_clock, index)
    db.get(Patient, patient.id).status = 'red'
    # A partial critical context must never pass as a complete usable snapshot.
    with pytest.raises(ValueError):
        service.clinical_snapshot(db, patient.id)


def test_critical_alerts_have_priority_over_more_recent_yellow_alerts(db, patient, edge_clock):
    red = [rule_alert(db, patient, edge_clock, index) for index in range(20)]
    for index in range(5):
        db.add(Alert(patient_id=patient.id, level='yellow', category='scale_threshold',
                     reason='Синтетическая повышенная сумма.', source='rule:phq9-score',
                     fingerprint=f'{patient.id}:synthetic-score:{index}', created_at=edge_clock))
    db.flush()
    _, snapshot = service.clinical_snapshot(db, patient.id)
    assert {a['id'] for a in snapshot['active_alerts']} == {a.id for a in red}
    assert snapshot['alert_counts'] == {'red': 20, 'yellow': 5}


@pytest.mark.parametrize('patient_summary', [
    'Данные переданы врачу. Продолжайте отмечать самочувствие.',
    'Заполните дневник. ' + CRITICAL_ASSESSMENT_NOTICE,
])
def test_correct_red_evidence_cannot_publish_patient_summary_without_leading_urgency(db, patient, edge_clock, patient_summary):
    original = rule_alert(db, patient, edge_clock, 0)
    db.get(Patient, patient.id).status = 'red'
    model = EvidenceModel([{'level': 'red', 'description': 'Положительный пункт 9 требует срочной оценки.',
                            'evidence': [f'alert:{original.id}']}], patient_summary=patient_summary)
    with pytest.raises(ValueError, match='Пациентская сводка'):
        service.analyze_patient(db, patient.id, model)
    assert not db.scalars(select(AIAnalysis).where(AIAnalysis.patient_id == patient.id)).all()
    assert not db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')).all()
    assert db.get(Patient, patient.id).status == 'red'


def test_inconsistent_intake_cannot_import_evidence_from_another_patients_prescription(db, patient, doctor, edge_clock):
    other = User(email='other@synthetic-context.test', name='Другой пациент', role='patient', password_hash='unused')
    db.add(other)
    db.flush()
    db.add(Patient(id=other.id, doctor_id=doctor.id, monitoring_started_at=edge_clock))
    own = Prescription(patient_id=patient.id, doctor_id=doctor.id, created_at=edge_clock - timedelta(days=3))
    foreign = Prescription(patient_id=other.id, doctor_id=doctor.id, created_at=edge_clock - timedelta(days=3))
    db.add_all([own, foreign])
    db.flush()
    for row in (own, foreign):
        db.add(PrescriptionVersion(prescription_id=row.id, version=1,
                                   created_at=edge_clock - timedelta(days=3),
                                   data={'name': 'Синтетический препарат', 'dose': '10', 'unit': 'мг'}))
    valid = Intake(patient_id=patient.id, prescription_id=own.id, version=1,
                    scheduled_at=edge_clock - timedelta(hours=1), status='taken')
    # The schema has independent FKs; an importer/legacy row can be inconsistent.
    corrupt = Intake(patient_id=patient.id, prescription_id=foreign.id, version=1,
                      scheduled_at=edge_clock - timedelta(hours=1), status='skipped',
                      reason='Чужое сообщение, не относится к этому пациенту')
    db.add_all([valid, corrupt])
    db.flush()
    _, snapshot = service.clinical_snapshot(db, patient.id)
    assert [row['id'] for row in snapshot['intakes']] == [valid.id]
    assert f'intake:{corrupt.id}' not in snapshot['evidence_refs']
    assert {row['prescription_id'] for row in snapshot['treatment_versions']} == {own.id}


def test_ai_mirror_of_rule_does_not_keep_patient_red_after_clinician_dismisses_source(doctor_client, db, patient, edge_clock):
    original = rule_alert(db, patient, edge_clock, 0)
    db.get(Patient, patient.id).status = 'red'
    model = EvidenceModel([{'level': 'red', 'description': 'Требуется оценка положительного пункта 9.',
                            'evidence': [f'alert:{original.id}']}])
    analysis = service.analyze_patient(db, patient.id, model)
    db.commit()
    assert analysis.result['risks'][0]['evidence'] == [f'alert:{original.id}']
    result = doctor_client.post(f'/api/alerts/{original.id}/actions',
                                json={'action': 'dismissed', 'comment': 'Проведено интервью, результат сохранён.'})
    assert result.status_code == 200, result.text
    assert db.get(Patient, patient.id).status == 'green'
    # The analysis remains readable; its copy of the same rule is not a second finding.
    assert db.scalar(select(AIAnalysis).where(AIAnalysis.id == analysis.id)) is not None
    assert not db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')).all()


def test_rule_reference_does_not_hide_independent_evidence_in_same_risk(doctor_client, db, patient, edge_clock):
    original = rule_alert(db, patient, edge_clock, 0)
    db.get(Patient, patient.id).status = 'red'
    entry = Diary(patient_id=patient.id, created_at=edge_clock,
                   mood=4, anxiety=7, sleep=4, energy=4, wellbeing=4,
                   comment='Из-за тревоги не справлялся с обычными рабочими задачами.')
    db.add(entry)
    db.flush()
    model = EvidenceModel([
        {'level': 'red', 'description': 'Требуется оценка положительного пункта 9.',
         'evidence': [f'alert:{original.id}']},
        {'level': 'yellow', 'description': 'Отдельно обсудить сообщённые трудности с повседневными задачами.',
         'evidence': [f'diary:{entry.id}', f'alert:{original.id}']},
    ])
    service.analyze_patient(db, patient.id, model)
    db.commit()
    result = doctor_client.post(f'/api/alerts/{original.id}/actions',
                                json={'action': 'dismissed', 'comment': 'Проведено интервью по пункту 9.'})
    assert result.status_code == 200, result.text
    assert db.get(Patient, patient.id).status == 'yellow'
    independent = list(db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')))
    assert len(independent) == 1 and independent[0].level == 'yellow'


def test_originating_questionnaire_and_alert_are_one_rule_finding(doctor_client, db, patient, edge_clock):
    ensure_standard_templates(db)
    template = db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.kind == 'phq9'))
    form = Assignment(patient_id=patient.id, template_id=template.id, active=False,
                       due_at=edge_clock - timedelta(hours=1),
                       snapshot={'name': template.name, 'kind': 'phq9', 'version': 1, 'schema': template.schema})
    db.add(form)
    db.flush()
    answers = {f'q{i}': 0 for i in range(1, 10)} | {'q9': 1}
    answer = Response(patient_id=patient.id, assignment_id=form.id, score=1, answers=answers,
                       created_at=edge_clock - timedelta(hours=1))
    db.add(answer)
    db.flush()
    original = rule_alert(db, patient, edge_clock, 0)
    original.fingerprint = f'{patient.id}:phq9-item9:{answer.id}'
    db.get(Patient, patient.id).status = 'red'
    db.flush()
    model = EvidenceModel([{'level': 'red', 'description': 'Положительный пункт 9 требует оценки специалистом.',
                            'evidence': [f'alert:{original.id}', f'questionnaire:{answer.id}']}])
    analysis = service.analyze_patient(db, patient.id, model)
    db.commit()
    assert analysis.result['risks'][0]['evidence'] == [f'alert:{original.id}', f'questionnaire:{answer.id}']
    assert not db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')).all()
    result = doctor_client.post(f'/api/alerts/{original.id}/actions',
                                json={'action': 'dismissed', 'comment': 'Проведена оценка исходного ответа и сигнала.'})
    assert result.status_code == 200, result.text
    assert db.get(Patient, patient.id).status == 'green'


def test_budget_trimming_retains_historical_intake_version_and_current_treatment(db, patient, doctor, edge_clock):
    prescription = Prescription(patient_id=patient.id, doctor_id=doctor.id, current_version=6,
                                created_at=edge_clock - timedelta(days=14))
    db.add(prescription)
    db.flush()
    for version in range(1, 7):
        db.add(PrescriptionVersion(prescription_id=prescription.id, version=version,
                                   created_at=edge_clock - timedelta(days=14 - 2 * version),
                                   data={'name': 'Синтетический препарат', 'dose': str(version * 5),
                                         'unit': 'мг', 'times': ['09:00'], 'comment': 'Учебная заметка. ' * 60}))
    for index in range(10):
        db.add(Diary(patient_id=patient.id, created_at=edge_clock - timedelta(hours=index),
                     mood=5, anxiety=5, sleep=5, energy=5, wellbeing=5,
                     comment='Подробная синтетическая запись наблюдения. ' * 30))
    db.add_all([
        Intake(patient_id=patient.id, prescription_id=prescription.id, version=1,
               scheduled_at=edge_clock - timedelta(days=11), status='taken',
               reason='Комментарий к давней отметке. ' * 40),
        Intake(patient_id=patient.id, prescription_id=prescription.id, version=6,
               scheduled_at=edge_clock - timedelta(hours=1), status='taken',
               reason='Комментарий к последней отметке. ' * 40),
    ])
    db.flush()
    _, snapshot = service.clinical_snapshot(db, patient.id)
    assert len(snapshot['diary']) < 10  # This fixture must actually exercise the budget.
    versions = {(row['prescription_id'], row['version']): row for row in snapshot['treatment_versions']}
    assert versions[(prescription.id, 1)]['data']['dose'] == '5'
    assert versions[(prescription.id, 6)]['data']['dose'] == '30'
    assert all((row['prescription_id'], row['version']) in versions for row in snapshot['intakes'])
    assert f'treatment:{prescription.id}:1' in snapshot['evidence_refs']
    assert f'treatment:{prescription.id}:6' in snapshot['evidence_refs']


def test_repeat_analysis_deduplicates_reviewed_evidence_but_accepts_new_event(doctor_client, db, patient, edge_clock):
    first = Diary(patient_id=patient.id, created_at=edge_clock - timedelta(hours=1),
                   mood=4, anxiety=7, sleep=4, energy=4, wellbeing=4, comment='Тревога мешала работе.')
    db.add(first)
    db.flush()
    model = EvidenceModel([{'level': 'yellow', 'description': 'Сообщённая тревога требует обсуждения с врачом.',
                            'evidence': [f'diary:{first.id}']}])
    service.analyze_patient(db, patient.id, model)
    service.analyze_patient(db, patient.id, model)
    db.flush()
    alerts = list(db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')))
    assert len(alerts) == 1
    result = doctor_client.post(f'/api/alerts/{alerts[0].id}/actions',
                                json={'action': 'dismissed', 'comment': 'Обсуждена тревога и согласован план наблюдения.'})
    assert result.status_code == 200, result.text
    assert db.get(Patient, patient.id).status == 'green'
    service.analyze_patient(db, patient.id, model)
    assert db.get(Patient, patient.id).status == 'green'
    assert alerts[0].state == 'dismissed'
    second = Diary(patient_id=patient.id, created_at=edge_clock,
                    mood=4, anxiety=7, sleep=4, energy=4, wellbeing=4, comment='Повторно трудно работать из-за тревоги.')
    db.add(second)
    db.flush()
    model.risks[0]['evidence'] = [f'diary:{second.id}']
    service.analyze_patient(db, patient.id, model)
    db.flush()
    assert len(db.scalars(select(Alert).where(Alert.patient_id == patient.id, Alert.category == 'ai')).all()) == 2
    assert db.get(Patient, patient.id).status == 'yellow'
