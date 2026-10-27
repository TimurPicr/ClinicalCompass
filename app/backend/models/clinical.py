"""Persistent clinical workflow records. No automatic prescribing rules."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Record:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_id: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)


class Invitation(Record, Base):
    __tablename__ = "invitations"
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending")


class Scale(Record, Base):
    __tablename__ = "scales"
    __table_args__ = (UniqueConstraint("code", "version"),)
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(40))
    questions: Mapped[list] = mapped_column(JSON, default=list)
    scoring_key: Mapped[str | None] = mapped_column(String(64))
    interpretation: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_source: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(40), default="pending_validation")
    active: Mapped[bool] = mapped_column(default=False)


class QuestionnaireResult(Record, Base):
    __tablename__ = "questionnaire_results"
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scale_id: Mapped[int] = mapped_column(ForeignKey("scales.id"))
    scale_code: Mapped[str] = mapped_column(String(64))
    scale_version: Mapped[str] = mapped_column(String(40))
    answers: Mapped[list] = mapped_column(JSON)
    score: Mapped[int]
    max_score: Mapped[int]
    note: Mapped[str] = mapped_column(Text)


class Recommendation(Record, Base):
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("result_id", "code"),)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaire_results.id"))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)


class Alert(Record, Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("patient_id", "event_key"),)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryAttempt(Record, Base):
    __tablename__ = "delivery_attempts"
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(40), default="web_inbox")
    status: Mapped[str] = mapped_column(String(40), default="available_in_inbox")
    attempt: Mapped[int] = mapped_column(default=1)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class Drug(Record, Base):
    __tablename__ = "drugs"
    name: Mapped[str] = mapped_column(String(255))
    indications: Mapped[str] = mapped_column(Text, default="")
    contraindications: Mapped[str] = mapped_column(Text, default="")
    dosing: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    registration_number: Mapped[str] = mapped_column(String(100), default="")
    registered_rf: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(40), default="pending_validation")
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TreatmentPlan(Record, Base):
    __tablename__ = "treatment_plans"
    __table_args__ = (UniqueConstraint("patient_id", "version"),
                      CheckConstraint("status IN ('draft','active','superseded')", name="ck_plan_status"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int]
    title: Mapped[str] = mapped_column(String(255))
    instructions: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prescription(Record, Base):
    __tablename__ = "prescriptions"
    plan_id: Mapped[int] = mapped_column(ForeignKey("treatment_plans.id"), index=True)
    drug_id: Mapped[int] = mapped_column(ForeignKey("drugs.id"))
    regimen: Mapped[str] = mapped_column(Text)
    drug_snapshot: Mapped[dict] = mapped_column(JSON)


class AdherenceReport(Record, Base):
    __tablename__ = "adherence_reports"
    __table_args__ = (UniqueConstraint("plan_id", "report_date"),)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("treatment_plans.id"))
    report_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")


class AdverseEvent(Record, Base):
    __tablename__ = "adverse_events"
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("treatment_plans.id"))
    description: Mapped[str] = mapped_column(Text)
    onset_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)


class Message(Record, Base):
    __tablename__ = "messages"
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int]
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class ClinicalAlertRule(Record, Base):
    """No rules are seeded. Activation requires an expert-reviewed migration."""
    __tablename__ = "clinical_alert_rules"
    __table_args__ = (UniqueConstraint("code", "version"),)
    code: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(40))
    scale_code: Mapped[str] = mapped_column(String(64))
    scale_version: Mapped[str] = mapped_column(String(40))
    evaluator: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(40), default="pending_validation")
    active: Mapped[bool] = mapped_column(default=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiaryEntry(Record, Base):
    __tablename__ = "diary_entries"
    __table_args__ = (UniqueConstraint("patient_id", "entry_date"),)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_date: Mapped[str] = mapped_column(String(10))
    result_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_results.id"))
    text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiaryRevision(Record, Base):
    __tablename__ = "diary_revisions"
    entry_id: Mapped[int] = mapped_column(ForeignKey("diary_entries.id"), index=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_results.id"))
    text: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
