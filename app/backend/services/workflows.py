from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.models.clinical import Alert, DeliveryAttempt, AuditEvent, TreatmentPlan


def audit(db: Session, actor_id: int, patient_id: int | None, entity: str, entity_id: int,
          action: str, details: dict | None = None):
    db.add(AuditEvent(actor_id=actor_id, patient_id=patient_id, entity=entity,
                      entity_id=entity_id, action=action, details=details or {}))


def create_alert(db: Session, patient, kind: str, event_key: str, text: str, severity="info"):
    """Called while holding the patient's row lock. DB uniqueness is a second guard.

    Only explicit workflow events are enabled. Future clinical rules must be
    reviewed and versioned before calling this delivery boundary.
    """
    if not patient.doctor_id:
        raise HTTPException(409, "Сначала прикрепитесь к врачу")
    existing = db.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.event_key == event_key))
    if existing:
        return existing
    alert = Alert(patient_id=patient.id, doctor_id=patient.doctor_id, event_key=event_key,
                  kind=kind, severity=severity, text=text)
    db.add(alert)
    db.flush()
    db.add(DeliveryAttempt(alert_id=alert.id))
    audit(db, patient.id, patient.id, "alert", alert.id, "created", {"kind": kind})
    return alert


def patient_plan(db: Session, patient_id: int, plan_id: int, *, confirmed=True):
    plan = db.get(TreatmentPlan, plan_id)
    if not plan or plan.patient_id != patient_id or (confirmed and not plan.confirmed_at):
        raise HTTPException(404, "План не найден")
    return plan
