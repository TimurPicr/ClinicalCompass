from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.backend.core.security import Auth, DB, patient_access, require_doctor, require_patient
from app.backend.models.clinical import Alert, DeliveryAttempt
from app.backend.schemas.clinical import UrgentRequest
from app.backend.services.workflows import audit, create_alert

router = APIRouter(prefix="/api", tags=["Alerts"])


@router.post("/urgent-help", status_code=201)
def urgent(data: UrgentRequest, user: Auth, db: DB):
    require_patient(user)
    patient = patient_access(db, user, user.id, lock=True)
    alert = create_alert(db, patient, "urgent_help_requested", "urgent:" + data.event_key,
                         "Пациент явно запросил срочную связь с врачом", "critical")
    db.commit()
    db.refresh(alert)
    return {"alert": alert, "notice": "Запрос сохранён в кабинете врача. Доставка и время ответа не гарантированы. При угрозе жизни обратитесь в экстренные службы."}


@router.get("/alerts")
def alerts(user: Auth, db: DB, active_only: bool = False):
    require_doctor(user)
    query = select(Alert).where(Alert.doctor_id == user.id)
    if active_only:
        query = query.where(Alert.status == "active")
    return db.scalars(query.order_by(Alert.id.desc())).all()


@router.get("/patients/{patient_id}/alerts")
def patient_alerts(patient_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    return db.scalars(select(Alert).where(Alert.patient_id == patient_id).order_by(Alert.id.desc())).all()


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int, user: Auth, db: DB):
    require_doctor(user)
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.doctor_id == user.id).with_for_update())
    if not alert:
        raise HTTPException(404, "Предупреждение не найдено")
    patient_access(db, user, alert.patient_id)
    if alert.status == "active":
        alert.status = "acknowledged"
        alert.acknowledged_by, alert.acknowledged_at = user.id, datetime.now(timezone.utc)
        audit(db, user.id, alert.patient_id, "alert", alert.id, "acknowledged")
        db.commit()
    return {"id": alert.id, "status": alert.status}


@router.get("/alerts/{alert_id}/deliveries")
def deliveries(alert_id: int, user: Auth, db: DB):
    require_doctor(user)
    alert = db.get(Alert, alert_id)
    if not alert or alert.doctor_id != user.id:
        raise HTTPException(404, "Предупреждение не найдено")
    patient_access(db, user, alert.patient_id)
    return db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.alert_id == alert_id).order_by(DeliveryAttempt.id)).all()
