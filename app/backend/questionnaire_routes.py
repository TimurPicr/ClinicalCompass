"""Questionnaire templates, immutable assignment snapshots and patient responses.

Fixed questions/scoring live in questionnaires.py; this module owns HTTP and storage.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.backend.auth import current_user, doctor_user, accessible_patient
from app.backend.clinical_common import Input, ScheduleInput, aware, row_dict, lock_patient, patient_only
from app.backend.monitoring import record_event
from app.backend.questionnaires import standard_schema, validate_schema, validate_answers, severity_label
from database.connection import get_db
from database.models import Assignment, QuestionnaireTemplate, Response, User, utcnow

router = APIRouter()


class TemplateInput(Input):
    name: str = Field(min_length=1, max_length=200)
    form_schema: dict = Field(alias='schema')


class AssignmentInput(Input):
    template_id: int
    due_at: datetime
    schedule: dict = Field(default_factory=lambda: {'frequency': 'once'})

    @field_validator('due_at')
    @classmethod
    def require_zone(cls, value):
        if value.tzinfo is None:
            raise ValueError('Укажите часовой пояс даты')
        return value.astimezone(timezone.utc)

    @field_validator('schedule')
    @classmethod
    def valid_schedule(cls, value):
        if set(value) - {'frequency', 'times'} or value.get('frequency', 'once') not in {'once', 'daily', 'weekly'}:
            raise ValueError('Допустимое расписание: once, daily, weekly')
        if value.get('times'):
            ScheduleInput(times=value['times'])
        return value


class ResponseInput(Input):
    answers: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=80)


def ensure_standard_templates(db):
    """Called by startup/seed; never mutate an already assigned clinical scale."""
    for kind, name in [('phq9', 'PHQ-9'), ('gad7', 'GAD-7')]:
        if not db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.kind == kind, QuestionnaireTemplate.doctor_id.is_(None))):
            db.add(QuestionnaireTemplate(name=name, kind=kind, doctor_id=None, schema=standard_schema(kind), version=1))
    db.flush()


def response_dict(response, snapshot):
    result = row_dict(response)
    result['severity_label'] = severity_label(snapshot.get('kind'), response.score)
    return result


def assignment_dict(db, assignment):
    result = row_dict(assignment)
    result['responses'] = [response_dict(r, assignment.snapshot) for r in db.scalars(select(Response).where(Response.assignment_id == assignment.id).order_by(Response.created_at))]
    return result


@router.get('/templates')
def list_templates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    owner = user.id if user.role == 'doctor' else accessible_patient(db, user, user.id).doctor_id
    return [row_dict(t) for t in db.scalars(select(QuestionnaireTemplate).where(or_(QuestionnaireTemplate.doctor_id.is_(None), QuestionnaireTemplate.doctor_id == owner)).order_by(QuestionnaireTemplate.id))]


@router.post('/templates', status_code=201)
def create_template(payload: TemplateInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    template = QuestionnaireTemplate(doctor_id=user.id, name=payload.name.strip(), kind='custom', schema=validate_schema(payload.form_schema), version=1)
    db.add(template)
    db.commit()
    return row_dict(template)


@router.put('/templates/{template_id}')
def update_template(template_id: int, payload: TemplateInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    template = db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.id == template_id).with_for_update()
                         .execution_options(populate_existing=True))
    if not template or template.doctor_id != user.id:
        raise HTTPException(404, 'Пользовательский шаблон не найден')
    if template.kind != 'custom':
        raise HTTPException(403, 'Стандартную клиническую шкалу изменять нельзя')
    template.schema = validate_schema(payload.form_schema)
    template.name, template.version = payload.name.strip(), template.version + 1
    db.commit()
    return row_dict(template)


@router.get('/patients/{patient_id}/assignments')
def list_assignments(patient_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    accessible_patient(db, user, patient_id)
    return [assignment_dict(db, a) for a in db.scalars(select(Assignment).where(Assignment.patient_id == patient_id).order_by(Assignment.due_at))]


@router.post('/patients/{patient_id}/assignments', status_code=201)
def create_assignment(patient_id: int, payload: AssignmentInput, db: Session = Depends(get_db), user: User = Depends(doctor_user)):
    lock_patient(db, user, patient_id)
    template = db.get(QuestionnaireTemplate, payload.template_id)
    if not template or template.doctor_id not in {None, user.id}:
        raise HTTPException(404, 'Опросник не найден')
    snapshot = {'name': template.name, 'kind': template.kind, 'version': template.version, 'schema': deepcopy(template.schema)}
    assignment = Assignment(patient_id=patient_id, template_id=template.id, snapshot=snapshot, schedule=payload.schedule, due_at=payload.due_at)
    db.add(assignment)
    db.commit()
    return assignment_dict(db, assignment)


def next_due(assignment, now, zone):
    """Calendar recurrence in the patient's zone, preserving wall time across DST."""
    local_due = aware(assignment.due_at).astimezone(zone)
    step = 7 if assignment.schedule.get('frequency') == 'weekly' else 1
    local_now = now.astimezone(zone)
    clock_times = assignment.schedule.get('times') or [local_due.strftime('%H:%M')]
    # The next same-day slot is valid only after the previously assigned slot;
    # weekly schedules retain the original weekday as their calendar anchor.
    days_elapsed = max(0, (local_now.date() - local_due.date()).days)
    cycle_date = local_due.date() + timedelta(days=(days_elapsed // step) * step)
    for day_offset in (0, step):
        for clock_time in sorted(clock_times):
            candidate = datetime.combine(cycle_date + timedelta(days=day_offset), time.fromisoformat(clock_time), zone)
            if candidate > local_now and candidate > local_due:
                return candidate.astimezone(timezone.utc)
    raise ValueError('No future questionnaire schedule occurrence')


@router.post('/assignments/{assignment_id}/responses', status_code=201)
def submit_response(assignment_id: int, payload: ResponseInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    patient_only(user)
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, 'Задание не найдено')
    lock_patient(db, user, assignment.patient_id)
    assignment = db.scalar(select(Assignment).where(Assignment.id == assignment_id).with_for_update()
                           .execution_options(populate_existing=True))
    if payload.idempotency_key:
        existing = db.scalar(select(Response).where(Response.patient_id == user.id, Response.idempotency_key == payload.idempotency_key))
        if existing:
            if existing.assignment_id != assignment.id or existing.answers != payload.answers:
                raise HTTPException(409, 'Ключ повторного запроса уже использован для других ответов')
            return response_dict(existing, assignment.snapshot)
    if not assignment.active:
        raise HTTPException(409, 'Задание уже выполнено')
    latest = db.scalar(select(Response).where(Response.assignment_id == assignment.id).order_by(Response.created_at.desc()).limit(1))
    zone = ZoneInfo(user.timezone)
    if latest and utcnow() < aware(assignment.due_at):
        raise HTTPException(409, 'Следующее заполнение доступно в назначенное время')
    score = validate_answers(assignment.snapshot, payload.answers)
    response = Response(patient_id=assignment.patient_id, assignment_id=assignment.id, answers=deepcopy(payload.answers), score=score, idempotency_key=payload.idempotency_key)
    db.add(response)
    db.flush()
    if assignment.schedule.get('frequency', 'once') == 'once':
        assignment.active = False
    else:
        assignment.due_at = next_due(assignment, utcnow(), zone)
    record_event(db, assignment.patient_id, f'response:{response.id}')
    db.commit()
    return response_dict(response, assignment.snapshot)
