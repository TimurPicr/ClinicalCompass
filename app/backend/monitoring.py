"""Transparent risk rules, physician alert feedback and durable AI event enqueueing.

Submissions, immediate rules and queued AI jobs share a transaction. This module
never invokes a model or changes treatment. Rule provenance: docs/clinical-rules.md.
"""
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.backend.auth import doctor_user, accessible_patient
from app.backend.clinical_common import Input, aware, row_dict, lock_patient
from app.backend.config import settings
from app.backend.questionnaires import MANUAL_URL
from database.connection import get_db
from database.models import (AIJob, Alert, AlertAction, Assignment, Diary, Intake,
                             Patient, Prescription, Response, User, utcnow)

router = APIRouter()


class AlertInput(Input):
    action: Literal['seen', 'confirmed', 'dismissed']
    comment: str = Field(default='', max_length=5000)


def alert_dict(db, alert):
    result = row_dict(alert)
    result['actions'] = [row_dict(a) for a in db.scalars(select(AlertAction).where(AlertAction.alert_id == alert.id).order_by(AlertAction.created_at))]
    return result


@router.get('/patients/{patient_id}/alerts')
def list_alerts(patient_id: int, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    accessible_patient(db, user, patient_id)
    return [alert_dict(db, a) for a in db.scalars(select(Alert).where(Alert.patient_id == patient_id).order_by(Alert.created_at.desc()))]


@router.get('/alerts')
def all_alerts(db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    return [alert_dict(db, a) for a in db.scalars(select(Alert).join(Patient, Alert.patient_id == Patient.id).where(Patient.doctor_id == user.id).order_by(Alert.created_at.desc()))]


@router.post('/alerts/{alert_id}/actions')
def act_on_alert(alert_id: int, payload: AlertInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, 'Предупреждение не найдено')
    lock_patient(db, user, alert.patient_id)
    alert.state, alert.comment = payload.action, payload.comment
    db.add(AlertAction(alert_id=alert.id, actor_id=user.id, **payload.model_dump()))
    db.flush()
    evaluate_rules(db, alert.patient_id)
    db.commit()
    return alert_dict(db, alert)


def evaluate_rules(db, patient_id, now=None):
    """Persist evidence with stable fingerprints; never make treatment decisions.

    Clinical: PHQ/GAD >=10 prompts assessment; PHQ item 9 >0 prompts urgent
    human assessment, not a claim of imminent danger. Other thresholds are
    labelled operational/demo rules; see docs/clinical-rules.md.
    """
    now = aware(now) if now else utcnow()
    patient = db.scalar(select(Patient).where(Patient.id == patient_id).with_for_update()
                        .execution_options(populate_existing=True))
    if not patient:
        return []
    db.flush()
    active_fingerprints = set()
    triggered = []

    def add(level, category, reason, source, fingerprint, source_url=''):
        fingerprint = f'{patient_id}:{fingerprint}'
        active_fingerprints.add(fingerprint)
        alert = db.scalar(select(Alert).where(Alert.fingerprint == fingerprint))
        if not alert:
            alert = Alert(patient_id=patient_id, level=level, category=category, reason=reason, source=source, source_url=source_url, fingerprint=fingerprint)
            db.add(alert)
            db.flush()
        elif alert.state == 'resolved':
            alert.state = 'new'
        triggered.append(alert)
        return alert

    responses = list(db.execute(select(Response, Assignment).join(Assignment, Response.assignment_id == Assignment.id).where(Response.patient_id == patient_id, Assignment.patient_id == patient_id, Response.created_at <= now).order_by(Response.created_at.desc(), Response.id.desc())))
    latest_by_kind = {}
    for response, assignment in responses:
        kind = assignment.snapshot.get('kind')
        latest_by_kind.setdefault(kind, (response, assignment))
        # An unanswered critical finding stays visible until a clinician dismisses it.
        if kind == 'phq9' and response.answers.get('q9', 0) > 0:
            add('red', 'self_harm_screen', f'PHQ-9, вопрос 9: {response.answers["q9"]}. Требуется срочная оценка специалистом; ответ сам по себе не определяет непосредственную опасность. При непосредственной угрозе обратитесь за неотложной медицинской помощью. Приложение не обеспечивает круглосуточного наблюдения.', 'rule:phq9-item9', f'phq9-item9:{response.id}', MANUAL_URL)
    for kind in ['phq9', 'gad7']:
        if kind in latest_by_kind:
            response, assignment = latest_by_kind[kind]
            if response.score is not None and response.score >= 10:
                add('yellow', 'scale_threshold', f'{assignment.snapshot["name"]}: {response.score}; уровень симптомов требует клинической оценки. Скрининг не является диагнозом.', f'rule:{kind}-score', f'{kind}-score:{response.id}', MANUAL_URL)
    recent = list(db.scalars(select(Intake).join(Prescription, Intake.prescription_id == Prescription.id)
                            .where(Intake.patient_id == patient_id, Prescription.patient_id == patient_id,
                                   Intake.scheduled_at >= now - timedelta(days=7), Intake.scheduled_at <= now)))
    skipped = [i for i in recent if i.status == 'skipped']
    if len(skipped) >= 2:
        add('yellow', 'adherence', f'За 7 дней отмечены {len(skipped)} пропуска приёма. Организационное правило: уточнить трудности выполнения назначения.', 'rule:operational-adherence', f'skipped:{max(i.id for i in skipped)}')
    for intake in recent:
        if intake.side_effect.strip():
            add('yellow', 'side_effect', f'Со слов пациента: {intake.side_effect}. Выраженность {intake.severity}/10. Причинная связь с препаратом не установлена.', 'rule:reported-side-effect', f'side-effect:{intake.id}')
    overdue = list(db.scalars(select(Assignment).where(Assignment.patient_id == patient_id, Assignment.active.is_(True), Assignment.due_at < now - timedelta(hours=24))))
    for assignment in overdue:
        name = assignment.snapshot.get('name', 'Опросник')
        add('yellow', 'missing_questionnaire', f'Не выполнено задание «{name}»; просрочка более 24 часов. Организационное правило, не медицинский порог.', 'rule:operational-questionnaire', f'overdue-questionnaire:{assignment.id}:{aware(assignment.due_at).isoformat()}')
    last_diary = db.scalar(select(Diary).where(Diary.patient_id == patient_id, Diary.created_at <= now).order_by(Diary.created_at.desc(), Diary.id.desc()).limit(1))
    last_at = aware(last_diary.created_at) if last_diary else aware(patient.monitoring_started_at)
    if patient.diary_times and last_at and last_at < now - timedelta(hours=48):
        add('yellow', 'missing_diary', 'Нет записей дневника более 48 часов. Организационное правило; отсутствие данных не свидетельствует о стабильности состояния.', 'rule:operational-diary', f'missing-diary:{last_diary.id if last_diary else "start"}')
    # Synthetic marker is intentionally explicit and disabled with DEMO_RULES=false.
    if settings.demo_rules and last_diary and '[DEMO_CRITICAL]' in last_diary.comment:
        add('red', 'demo_critical', 'ДЕМОНСТРАЦИОННОЕ правило: в синтетическом дневнике указан маркер [DEMO_CRITICAL]. Это тест интерфейса, не клинический критерий.', 'rule:demo-critical', f'demo-critical:{last_diary.id}')
    alerts = list(db.scalars(select(Alert).where(Alert.patient_id == patient_id)))
    for alert in alerts:
        if alert.source.startswith('rule:') and alert.fingerprint not in active_fingerprints and alert.category != 'self_harm_screen' and alert.state not in {'dismissed', 'resolved'}:
            alert.state = 'resolved'
    active = [a for a in alerts if a.state not in {'dismissed', 'resolved'}]
    patient.status = 'red' if any(a.level == 'red' for a in active) else 'yellow' if any(a.level == 'yellow' for a in active) else 'green'
    db.flush()
    return triggered


def record_event(db, patient_id, key):
    """Caller commits data, rule results and one durable AI job atomically."""
    patient = db.get(Patient, patient_id)
    if not patient:
        raise ValueError('Patient does not exist')
    patient.last_activity = utcnow()
    db.flush()
    evaluate_rules(db, patient_id)
    dedupe_key = f'clinical:{patient_id}:{key}'
    if not db.scalar(select(AIJob).where(AIJob.dedupe_key == dedupe_key)):
        db.add(AIJob(patient_id=patient_id, kind='analysis', payload={'event': key}, dedupe_key=dedupe_key))
    db.flush()
