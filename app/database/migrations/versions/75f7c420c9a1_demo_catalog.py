"""Seed demo content; clinical scales and Aviandr stay inactive.

Revision ID: 75f7c420c9a1
Revises: 6294c3b6707c
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "75f7c420c9a1"
down_revision = "6294c3b6707c"
branch_labels = None
depends_on = None


QUESTIONS = [
    {"id": 1, "text": "Как часто вам было трудно сосредоточиться?", "options": ["Никогда", "Редко", "Часто", "Почти всегда"]},
    {"id": 2, "text": "Как часто вы испытывали беспокойство?", "options": ["Никогда", "Редко", "Часто", "Почти всегда"]},
    {"id": 3, "text": "Как часто вам было трудно заснуть?", "options": ["Никогда", "Редко", "Часто", "Почти всегда"]},
    {"id": 4, "text": "Как часто вы испытывали недостаток энергии?", "options": ["Никогда", "Редко", "Часто", "Почти всегда"]},
    {"id": 5, "text": "Как часто вам было трудно выполнять обычные дела?", "options": ["Никогда", "Редко", "Часто", "Почти всегда"]},
]


def upgrade():
    scales = sa.table("scales", sa.column("code", sa.String), sa.column("title", sa.String),
                      sa.column("version", sa.String), sa.column("questions", sa.JSON),
                      sa.column("scoring_key", sa.String), sa.column("interpretation", sa.JSON),
                      sa.column("validation_source", sa.Text), sa.column("license", sa.Text),
                      sa.column("review_status", sa.String), sa.column("active", sa.Boolean),
                      sa.column("created_at", sa.DateTime(timezone=True)))
    now = datetime.now(timezone.utc)
    common = dict(version="1", questions=[], scoring_key=None, interpretation={},
                  validation_source=None, license=None, review_status="pending_validation", active=False, created_at=now)
    op.bulk_insert(scales, [
        {**common, "code": "demo", "title": "Учебный опросник самочувствия", "questions": QUESTIONS,
         "scoring_key": "demo_sum_v1", "review_status": "demo_only", "active": True,
         "validation_source": "Внутренний учебный пример: app/backend/services/questionnaire_service.py; клинической валидации нет",
         "license": "Учебный контент проекта; права на внешние клинические шкалы не заявляются"},
        {**common, "code": "phq-9", "title": "PHQ-9 — ожидает проверки русскоязычной версии и лицензии"},
        {**common, "code": "gad-7", "title": "GAD-7 — ожидает проверки русскоязычной версии и лицензии"},
    ])
    drugs = sa.table("drugs", sa.column("name", sa.String), sa.column("indications", sa.Text),
                     sa.column("contraindications", sa.Text), sa.column("dosing", sa.Text),
                     sa.column("source_url", sa.Text), sa.column("registration_number", sa.String),
                     sa.column("registered_rf", sa.Boolean), sa.column("status", sa.String),
                     sa.column("created_at", sa.DateTime(timezone=True)))
    op.bulk_insert(drugs, [dict(name="Авиандр", indications="", contraindications="", dosing="", source_url="",
                               registration_number="", registered_rf=False, status="pending_validation", created_at=now)])


def downgrade():
    # FK constraints deliberately prevent deleting catalog records already in use.
    op.execute(sa.text("DELETE FROM drugs WHERE name = 'Авиандр' AND status = 'pending_validation' AND source_url = ''"))
    op.execute(sa.text("DELETE FROM scales WHERE code IN ('demo', 'phq-9', 'gad-7') AND version = '1'"))
