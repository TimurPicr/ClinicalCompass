"""Clinical/operational scenarios: evidence chronology, independent risks and review.

These tests verify implemented routing rules, not clinical effectiveness or a
suicide prediction model. All records are synthetic and the clock is fixed.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.backend import monitoring
from app.backend.questionnaire_routes import ensure_standard_templates
from database.models import (Alert, AlertAction, Assignment, Diary, Intake, Patient,
                             Prescription, PrescriptionVersion, QuestionnaireTemplate,
                             Response, User)


@pytest.fixture
def clock(db, patient, monkeypatch):
    now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(monitoring, 'utcnow', lambda: now)
    db.get(Patient, patient.id).monitoring_started_at = now - timedelta(hours=1)
    db.flush()
    return now


def assignment(db, patient, now, kind='phq9', *, active=False, due_at=None):
    ensure_standard_templates(db)
    template = db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.kind == kind))
    row = Assignment(patient_id=patient.id, template_id=template.id,
                     snapshot={'name': template.name, 'kind': kind, 'version': 1, 'schema': template.schema},
                     schedule={'frequency': 'weekly'}, active=active, due_at=due_at or now)
    db.add(row)
    db.flush()
    return row


def response(db, patient, now, *, kind='phq9', score=0, q9=0, form=None):
    form = form or assignment(db, patient, now, kind)
    count = 9 if kind == 'phq9' else 7
    answers = {f'q{i}': 0 for i in range(1, count + 1)}
    remaining = score - (q9 if kind == 'phq9' else 0)
    for i in range(1, 9 if kind == 'phq9' else 8):
        answers[f'q{i}'] = min(3, remaining)
        remaining -= answers[f'q{i}']
    assert remaining == 0
    if kind == 'phq9':
        answers['q9'] = q9
    row = Response(patient_id=patient.id, assignment_id=form.id, answers=answers,
                   score=sum(answers.values()), created_at=now)
    db.add(row)
    db.flush()
    return row


def diary(db, patient, now, **values):
    row = Diary(patient_id=patient.id, created_at=now,
                **({'mood': 7, 'anxiety': 2, 'sleep': 7, 'energy': 7, 'wellbeing': 7,
                    'comment': ''} | values))
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def prescription(db, patient, doctor, clock):
    row = Prescription(patient_id=patient.id, doctor_id=doctor.id,
                       created_at=clock - timedelta(days=14))
    db.add(row)
    db.flush()
    db.add(PrescriptionVersion(prescription_id=row.id, version=1,
                              created_at=clock - timedelta(days=14),
                              data={'name': 'Синтетическое назначение', 'dose': '10', 'unit': 'мг',
                                    'times': ['09:00'], 'start_date': (clock - timedelta(days=14)).date().isoformat()}))
    db.flush()
    return row


def intake(db, patient, prescription, when, *, status='taken', side_effect=''):
    row = Intake(patient_id=patient.id, prescription_id=prescription.id, version=1,
                 scheduled_at=when, actual_at=when if status == 'taken' else None,
                 status=status, side_effect=side_effect, severity=4 if side_effect else 0)
    db.add(row)
    db.flush()
    return row


def active_alerts(db, patient, *, category=None):
    rows = list(db.scalars(select(Alert).where(Alert.patient_id == patient.id)))
    return [a for a in rows if a.state not in {'dismissed', 'resolved'}
            and (category is None or a.category == category)]


@pytest.mark.parametrize('kind,score,status', [
    ('phq9', 0, 'green'), ('phq9', 9, 'green'), ('phq9', 10, 'yellow'), ('phq9', 24, 'yellow'),
    ('gad7', 0, 'green'), ('gad7', 9, 'green'), ('gad7', 10, 'yellow'), ('gad7', 21, 'yellow'),
])
def test_scale_boundaries_do_not_confuse_screening_score_with_immediate_risk(db, patient, clock, kind, score, status):
    response(db, patient, clock, kind=kind, score=score)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert db.get(Patient, patient.id).status == status
    assert not active_alerts(db, patient, category='self_harm_screen')
    for alert in active_alerts(db, patient):
        assert alert.source == f'rule:{kind}-score'
        assert 'не является диагнозом' in alert.reason


@pytest.mark.parametrize('q9', [1, 2, 3])
def test_positive_item9_is_red_even_when_total_is_below_screening_threshold(db, patient, clock, q9):
    answer = response(db, patient, clock, score=q9, q9=q9)
    monitoring.evaluate_rules(db, patient.id, clock)
    alerts = active_alerts(db, patient)
    assert len(alerts) == 1 and alerts[0].level == 'red'
    assert alerts[0].fingerprint.endswith(f'phq9-item9:{answer.id}')
    assert 'сам по себе не определяет непосредственную опасность' in alerts[0].reason
    assert db.get(Patient, patient.id).status == 'red'


def test_latest_score_is_selected_per_instrument_and_ties_use_response_id(db, patient, clock):
    response(db, patient, clock - timedelta(days=2), kind='gad7', score=17)
    response(db, patient, clock - timedelta(days=1), score=16)
    response(db, patient, clock, score=10)
    response(db, patient, clock, score=4)  # Same timestamp, later stored answer.
    monitoring.evaluate_rules(db, patient.id, clock)
    assert {a.source for a in active_alerts(db, patient)} == {'rule:gad7-score'}
    response(db, patient, clock, kind='gad7', score=4)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)
    assert db.get(Patient, patient.id).status == 'green'


def test_future_answers_neither_trigger_nor_clear_current_findings(db, patient, clock):
    response(db, patient, clock - timedelta(hours=1), score=12)
    response(db, patient, clock + timedelta(hours=1), score=0)
    response(db, patient, clock + timedelta(hours=2), score=1, q9=1)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert {a.source for a in active_alerts(db, patient)} == {'rule:phq9-score'}
    assert db.get(Patient, patient.id).status == 'yellow'
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(hours=1))
    assert db.get(Patient, patient.id).status == 'green'
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(hours=2))
    assert db.get(Patient, patient.id).status == 'red'


@pytest.mark.parametrize('action', ['seen', 'confirmed'])
def test_reviewing_critical_signal_keeps_it_open_despite_later_good_data(doctor_client, db, patient, doctor, clock, action):
    response(db, patient, clock - timedelta(days=3), score=1, q9=1)
    response(db, patient, clock, score=0)
    diary(db, patient, clock, mood=9, anxiety=0, wellbeing=9)
    monitoring.evaluate_rules(db, patient.id, clock)
    alert = active_alerts(db, patient, category='self_harm_screen')[0]
    result = doctor_client.post(f'/api/alerts/{alert.id}/actions',
                                json={'action': action, 'comment': 'Сигнал оценён, наблюдение продолжается'})
    assert result.status_code == 200, result.text
    assert result.json()['state'] == action
    assert db.get(Patient, patient.id).status == 'red'
    assert db.scalar(select(AlertAction).where(AlertAction.alert_id == alert.id)).actor_id == doctor.id


def test_dismissing_one_critical_event_does_not_dismiss_another_or_future_event(doctor_client, db, patient, clock):
    response(db, patient, clock - timedelta(days=2), score=1, q9=1)
    response(db, patient, clock - timedelta(days=1), score=2, q9=2)
    monitoring.evaluate_rules(db, patient.id, clock)
    alerts = active_alerts(db, patient, category='self_harm_screen')
    assert len(alerts) == 2
    for index, alert in enumerate(alerts):
        result = doctor_client.post(f'/api/alerts/{alert.id}/actions',
                                    json={'action': 'dismissed', 'comment': 'Результат очной оценки сохранён'})
        assert result.status_code == 200
        assert db.get(Patient, patient.id).status == ('red' if index == 0 else 'green')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)
    response(db, patient, clock, score=1, q9=1)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert len(active_alerts(db, patient, category='self_harm_screen')) == 1
    assert db.get(Patient, patient.id).status == 'red'


def test_independent_operational_and_ai_signals_survive_critical_dismissal(doctor_client, db, patient, prescription, clock):
    response(db, patient, clock, score=12, q9=1)
    intake(db, patient, prescription, clock - timedelta(days=2), status='skipped')
    intake(db, patient, prescription, clock - timedelta(days=1), status='skipped')
    intake(db, patient, prescription, clock, side_effect='Тошнота после еды')
    ai_alert = Alert(patient_id=patient.id, level='yellow', category='ai', reason='Гипотеза, требует оценки',
                     source='AIAnalysis:synthetic', fingerprint=f'ai-synthetic:{patient.id}')
    db.add(ai_alert)
    monitoring.evaluate_rules(db, patient.id, clock)
    critical = active_alerts(db, patient, category='self_harm_screen')[0]
    assert doctor_client.post(f'/api/alerts/{critical.id}/actions',
                             json={'action': 'dismissed', 'comment': 'Проведено интервью'}).status_code == 200
    assert db.get(Patient, patient.id).status == 'yellow'
    assert {a.category for a in active_alerts(db, patient)} == {'scale_threshold', 'adherence', 'side_effect', 'ai'}
    response(db, patient, clock, score=0)
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(days=8))
    assert {a.category for a in active_alerts(db, patient)} == {'ai', 'missing_diary'}
    assert ai_alert.state == 'new'  # Deterministic rules cannot resolve AI evidence.


def test_missing_intake_records_are_not_inferred_as_skipped_doses(db, patient, prescription, clock):
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient, category='adherence')
    intake(db, patient, prescription, clock - timedelta(days=1), status='skipped')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient, category='adherence')
    intake(db, patient, prescription, clock - timedelta(hours=1), status='taken')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert db.get(Patient, patient.id).status == 'green'


def test_adherence_window_includes_seven_day_boundary_and_excludes_old_and_future_records(db, patient, prescription, clock):
    intake(db, patient, prescription, clock - timedelta(days=7, microseconds=1), status='skipped')
    intake(db, patient, prescription, clock + timedelta(seconds=1), status='skipped')
    intake(db, patient, prescription, clock - timedelta(days=7), status='skipped')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient, category='adherence')
    intake(db, patient, prescription, clock, status='skipped')
    monitoring.evaluate_rules(db, patient.id, clock)
    alert = active_alerts(db, patient, category='adherence')[0]
    assert '2 пропуска' in alert.reason
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(microseconds=1))
    assert not active_alerts(db, patient, category='adherence')
    assert alert.state == 'resolved'


@pytest.mark.parametrize('offset,expected', [
    (timedelta(days=-7, microseconds=-1), False),
    (timedelta(days=-7), True),
    (timedelta(), True),
    (timedelta(seconds=1), False),
])
def test_side_effect_is_a_report_with_uncertain_causality_within_current_window(db, patient, prescription, clock, offset, expected):
    intake(db, patient, prescription, clock + offset, side_effect='Головокружение')
    monitoring.evaluate_rules(db, patient.id, clock)
    alerts = active_alerts(db, patient, category='side_effect')
    assert bool(alerts) is expected
    if alerts:
        assert alerts[0].level == 'yellow'
        assert 'Причинная связь с препаратом не установлена' in alerts[0].reason


@pytest.mark.parametrize('age,expected', [
    (timedelta(hours=48), False), (timedelta(hours=48, microseconds=1), True),
])
def test_missing_diary_strict_boundary(db, patient, clock, age, expected):
    diary(db, patient, clock - age)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert bool(active_alerts(db, patient, category='missing_diary')) is expected


@pytest.mark.parametrize('age,active,expected', [
    (timedelta(hours=24), True, False),
    (timedelta(hours=24, microseconds=1), True, True),
    (timedelta(days=3), False, False),
])
def test_only_active_questionnaire_more_than_24_hours_overdue_triggers(db, patient, clock, age, active, expected):
    assignment(db, patient, clock, active=active, due_at=clock - age)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert bool(active_alerts(db, patient, category='missing_questionnaire')) is expected


def test_future_diary_cannot_hide_missing_data_or_raise_demo_signal(db, patient, clock, monkeypatch):
    monkeypatch.setattr(monitoring.settings, 'demo_rules', True)
    db.get(Patient, patient.id).monitoring_started_at = clock - timedelta(days=4)
    diary(db, patient, clock + timedelta(days=1), comment='[DEMO_CRITICAL]')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert {a.category for a in active_alerts(db, patient)} == {'missing_diary'}
    assert db.get(Patient, patient.id).status == 'yellow'


def test_unassigned_diary_does_not_generate_missing_data_signal(db, patient, clock):
    row = db.get(Patient, patient.id)
    row.diary_times = []
    row.monitoring_started_at = clock - timedelta(days=90)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)


def test_new_gap_in_diary_is_not_silenced_by_prior_dismissal(doctor_client, db, patient, clock):
    diary(db, patient, clock - timedelta(days=4))
    monitoring.evaluate_rules(db, patient.id, clock)
    first = active_alerts(db, patient, category='missing_diary')[0]
    assert doctor_client.post(f'/api/alerts/{first.id}/actions',
                             json={'action': 'dismissed', 'comment': 'Уточнено по телефону'}).status_code == 200
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)
    diary(db, patient, clock)
    monitoring.evaluate_rules(db, patient.id, clock)
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(days=3))
    second = active_alerts(db, patient, category='missing_diary')[0]
    assert first.id != second.id and first.state == 'dismissed'
    assert db.get(Patient, patient.id).status == 'yellow'
    # Repeating evaluation for the same episode must not duplicate it.
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(days=3))
    assert len(active_alerts(db, patient, category='missing_diary')) == 1


def test_new_questionnaire_and_next_recurring_cycle_are_not_silenced_by_prior_dismissal(doctor_client, db, patient, clock):
    form = assignment(db, patient, clock, active=True, due_at=clock - timedelta(days=2))
    monitoring.evaluate_rules(db, patient.id, clock)
    first = active_alerts(db, patient, category='missing_questionnaire')[0]
    assert doctor_client.post(f'/api/alerts/{first.id}/actions',
                             json={'action': 'dismissed', 'comment': 'Согласован перенос'}).status_code == 200
    form.due_at = clock + timedelta(days=1)
    monitoring.evaluate_rules(db, patient.id, clock)
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(days=3))
    next_cycle = active_alerts(db, patient, category='missing_questionnaire')[0]
    assert next_cycle.id != first.id and first.state == 'dismissed'
    assignment(db, patient, clock, kind='gad7', active=True, due_at=clock - timedelta(days=2))
    monitoring.evaluate_rules(db, patient.id, clock + timedelta(days=3))
    assert len(active_alerts(db, patient, category='missing_questionnaire')) == 2


def test_extreme_diary_values_are_not_undocumented_critical_thresholds(db, patient, clock):
    diary(db, patient, clock, mood=0, anxiety=10, sleep=0, energy=0, wellbeing=0)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)
    assert db.get(Patient, patient.id).status == 'green'


def test_patient_evidence_and_review_are_isolated(doctor_client, db, patient, doctor, other_doctor, clock):
    other = User(email='other-patient@synthetic.test', name='Другой синтетический пациент',
                 role='patient', password_hash='unused')
    db.add(other)
    db.flush()
    db.add(Patient(id=other.id, doctor_id=other_doctor.id, monitoring_started_at=clock))
    response(db, other, clock, score=1, q9=1)
    monitoring.evaluate_rules(db, other.id, clock)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert db.get(Patient, patient.id).status == 'green'
    other_alert = active_alerts(db, other)[0]
    assert doctor_client.get(f'/api/patients/{other.id}/alerts').status_code == 404
    assert doctor_client.post(f'/api/alerts/{other_alert.id}/actions',
                             json={'action': 'dismissed', 'comment': 'Недопустимое действие'}).status_code == 404
    assert other_alert.state == 'new'
    assert not db.scalars(select(AlertAction)).all()


def other_patient(db, doctor, clock):
    row = User(email='other-import@synthetic.test', name='Другой синтетический пациент',
               role='patient', password_hash='unused')
    db.add(row)
    db.flush()
    db.add(Patient(id=row.id, doctor_id=doctor.id, monitoring_started_at=clock))
    db.flush()
    return row


@pytest.mark.parametrize('kind,score,q9', [('phq9', 1, 1), ('phq9', 12, 0), ('gad7', 14, 0)])
def test_response_linked_to_foreign_assignment_cannot_create_screening_signal(db, patient, doctor, clock, kind, score, q9):
    other = other_patient(db, doctor, clock)
    foreign_form = assignment(db, other, clock, kind=kind)
    # Independent FKs permit inconsistent rows from direct imports/legacy seeds.
    response(db, patient, clock, kind=kind, score=score, q9=q9, form=foreign_form)
    monitoring.evaluate_rules(db, patient.id, clock)
    monitoring.evaluate_rules(db, other.id, clock)
    assert not active_alerts(db, patient)
    assert not active_alerts(db, other)
    assert db.get(Patient, patient.id).status == 'green'
    assert db.get(Patient, other.id).status == 'green'


@pytest.mark.parametrize('kind', ['phq9', 'gad7'])
def test_response_linked_to_foreign_assignment_cannot_clear_legitimate_scale_signal(db, patient, doctor, clock, kind):
    response(db, patient, clock - timedelta(hours=1), kind=kind, score=12)
    monitoring.evaluate_rules(db, patient.id, clock)
    original = active_alerts(db, patient, category='scale_threshold')[0]
    other = other_patient(db, doctor, clock)
    foreign_form = assignment(db, other, clock, kind=kind)
    response(db, patient, clock, kind=kind, score=0, form=foreign_form)
    monitoring.evaluate_rules(db, patient.id, clock)
    assert [a.id for a in active_alerts(db, patient)] == [original.id]
    assert original.state == 'new'
    assert db.get(Patient, patient.id).status == 'yellow'


def test_intakes_linked_to_foreign_prescription_do_not_contribute_skips_or_side_effects(db, patient, doctor, prescription, clock):
    other = other_patient(db, doctor, clock)
    foreign = Prescription(patient_id=other.id, doctor_id=doctor.id, created_at=clock - timedelta(days=7))
    db.add(foreign)
    db.flush()
    intake(db, patient, prescription, clock - timedelta(days=2), status='skipped')
    intake(db, patient, foreign, clock - timedelta(days=2), status='skipped', side_effect='Чужая жалоба')
    intake(db, patient, foreign, clock - timedelta(days=1), status='skipped')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert not active_alerts(db, patient)
    assert db.get(Patient, patient.id).status == 'green'
    # Correctly linked new evidence must still raise both independent signals.
    intake(db, patient, prescription, clock - timedelta(days=1), status='skipped')
    intake(db, patient, prescription, clock, side_effect='Собственная жалоба')
    monitoring.evaluate_rules(db, patient.id, clock)
    assert {a.category for a in active_alerts(db, patient)} == {'adherence', 'side_effect'}
    assert '2 пропуска' in active_alerts(db, patient, category='adherence')[0].reason
    assert 'Собственная жалоба' in active_alerts(db, patient, category='side_effect')[0].reason
