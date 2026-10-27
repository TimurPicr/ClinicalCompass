"""Small shared validation, UTC and patient-access helpers for clinical features."""
from datetime import timezone
import re
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from app.backend.auth import accessible_patient
from database.models import Patient


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def row_dict(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def lock_patient(db, user, patient_id):
    accessible_patient(db, user, patient_id)
    # A row may already be cached before this lock waited for another writer.
    # Refresh its values after acquiring the lock, otherwise JSON merges lose
    # that writer's changes despite PostgreSQL correctly serializing the SQL.
    return db.scalar(select(Patient).where(Patient.id == patient_id).with_for_update()
                     .execution_options(populate_existing=True))


def patient_only(user):
    if user.role != 'patient':
        raise HTTPException(403, 'Ответы и самонаблюдение заполняет пациент')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ScheduleInput(Input):
    times: list[str] = Field(min_length=1, max_length=8)

    @field_validator('times')
    @classmethod
    def valid_times(cls, values):
        if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) for value in values):
            raise ValueError('Укажите время в формате ЧЧ:ММ')
        if len(set(values)) != len(values):
            raise ValueError('Время не должно повторяться')
        return sorted(values)
