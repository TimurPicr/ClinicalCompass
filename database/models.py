"""Tables grouped by feature. JSON stores immutable form/analysis snapshots."""
from datetime import date, datetime, timezone
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
                        Integer, JSON, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def utcnow():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class Timestamp:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class User(Timestamp, Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), default='Europe/Moscow')
    __table_args__ = (CheckConstraint("role IN ('doctor','patient')"),)

class AuthSession(Timestamp, Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class Invitation(Timestamp, Base):
    __tablename__ = 'invitations'
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ResetToken(Timestamp, Base):
    __tablename__ = 'reset_tokens'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Patient(Base):
    __tablename__ = 'patients'
    id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    monitoring_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    diary_times: Mapped[list] = mapped_column(JSON, default=lambda: ['20:00'])
    record: Mapped[dict] = mapped_column(JSON, default=dict)
    reported_record: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default='green', index=True)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('id != doctor_id'), CheckConstraint("status IN ('green','yellow','red')"))

class Audit(Timestamp, Base):
    __tablename__ = 'audits'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)

class QuestionnaireTemplate(Timestamp, Base):
    __tablename__ = 'questionnaire_templates'
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default='custom')
    schema: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)

class Assignment(Timestamp, Base):
    __tablename__ = 'assignments'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey('questionnaire_templates.id', ondelete='RESTRICT'))
    snapshot: Mapped[dict] = mapped_column(JSON)
    schedule: Mapped[dict] = mapped_column(JSON, default=dict)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Response(Timestamp, Base):
    __tablename__ = 'responses'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey('assignments.id', ondelete='RESTRICT'), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    score: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint('patient_id', 'idempotency_key'),)

class Prescription(Timestamp, Base):
    __tablename__ = 'prescriptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class PrescriptionVersion(Timestamp, Base):
    __tablename__ = 'prescription_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id', ondelete='RESTRICT'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('prescription_id','version'),)

class Intake(Base):
    __tablename__ = 'intakes'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey('prescriptions.id', ondelete='RESTRICT'))
    version: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default='')
    side_effect: Mapped[str] = mapped_column(Text, default='')
    severity: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint('prescription_id','scheduled_at'), CheckConstraint("status IN ('taken','skipped')"), CheckConstraint('severity BETWEEN 0 AND 10'))

class Diary(Timestamp, Base):
    __tablename__ = 'diary'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    mood: Mapped[int] = mapped_column(Integer)
    anxiety: Mapped[int] = mapped_column(Integer)
    sleep: Mapped[int] = mapped_column(Integer)
    energy: Mapped[int] = mapped_column(Integer)
    wellbeing: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = tuple(CheckConstraint(f'{x} BETWEEN 0 AND 10') for x in ['mood','anxiety','sleep','energy','wellbeing'])

class Alert(Timestamp, Base):
    __tablename__ = 'alerts'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    level: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(160))
    source_url: Mapped[str] = mapped_column(Text, default='')
    fingerprint: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(16), default='new')
    comment: Mapped[str] = mapped_column(Text, default='')

class AlertAction(Timestamp, Base):
    __tablename__ = 'alert_actions'
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey('alerts.id', ondelete='RESTRICT'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    action: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text, default='')

class AIJob(Timestamp, Base):
    __tablename__ = 'ai_jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    kind: Mapped[str] = mapped_column(String(32), default='analysis')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AIAnalysis(Timestamp, Base):
    __tablename__ = 'ai_analyses'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    result: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(100))

class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    published_at: Mapped[str | None] = mapped_column(String(80))
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)
    checksum: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('source','external_id','version'), Index('ix_knowledge_identity','source','external_id','active'))

class Chunk(Base):
    __tablename__ = 'chunks'
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='RESTRICT'), index=True)
    page: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(Vector(1024).with_variant(JSON, 'sqlite'))
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint('document_id','position'),)

class SourceLog(Timestamp, Base):
    __tablename__ = 'source_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)

class Document(Timestamp, Base):
    __tablename__ = 'documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    name: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str] = mapped_column(Text, default='')
    extraction: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default='pending')

class ChatAttachment(Timestamp, Base):
    __tablename__ = 'chat_attachments'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    name: Mapped[str] = mapped_column(String(255))
    storage_name: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)

class Message(Timestamp, Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    text: Mapped[str] = mapped_column(Text, default='')
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey('chat_attachments.id', ondelete='RESTRICT'), unique=True)

class PushSubscription(Timestamp, Base):
    __tablename__ = 'push_subscriptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSON)

class Reminder(Timestamp, Base):
    __tablename__ = 'reminders'
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey('patients.id', ondelete='RESTRICT'))
    key: Mapped[str] = mapped_column(String(200), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
