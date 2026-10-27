from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.backend.core.security import Auth, DB, patient_access, require_doctor
from app.backend.models.clinical import Drug, TreatmentPlan, Prescription, AuditEvent
from app.backend.schemas.clinical import PlanInput, DrugInput, DrugVerification
from app.backend.services.workflows import audit

router = APIRouter(prefix="/api", tags=["Treatments"])


def drug_data(drug):
    return {"id": drug.id, "name": drug.name, "indications": drug.indications,
            "contraindications": drug.contraindications, "dosing": drug.dosing,
            "source_url": drug.source_url, "registration_number": drug.registration_number,
            "registered_rf": drug.registered_rf, "verified_by": drug.verified_by,
            "verified_at": drug.verified_at.isoformat() if drug.verified_at else None,
            "status": drug.status}


@router.get("/drugs")
def drugs(user: Auth, db: DB):
    require_doctor(user)
    return db.scalars(select(Drug).order_by(Drug.id)).all()


@router.post("/drugs", status_code=201)
def create_drug(data: DrugInput, user: Auth, db: DB):
    require_doctor(user)
    drug = Drug(**data.model_dump())
    db.add(drug)
    db.flush()
    audit(db, user.id, None, "drug", drug.id, "created_pending_validation")
    db.commit()
    db.refresh(drug)
    return drug


@router.post("/drugs/{drug_id}/verify")
def verify_drug(drug_id: int, data: DrugVerification, user: Auth, db: DB):
    """Explicit professional attestation; the software does not verify GRLS contents."""
    require_doctor(user)
    drug = db.scalar(select(Drug).where(Drug.id == drug_id).with_for_update())
    if not drug:
        raise HTTPException(404, "Препарат не найден")
    if drug.status != "pending_validation":
        raise HTTPException(409, "Запись уже проверена")
    # The preseeded placeholder cannot be approved without a complete new record.
    try:
        DrugInput(**{key: getattr(drug, key) for key in DrugInput.model_fields})
    except ValidationError:
        raise HTTPException(409, "Добавьте полную запись из действующей инструкции ГРЛС") from None
    drug.registered_rf, drug.status = True, "verified"
    drug.verified_at, drug.verified_by = datetime.now(timezone.utc), user.id
    audit(db, user.id, None, "drug", drug.id, "verified_by_doctor", {"comment": data.comment})
    db.commit()
    db.refresh(drug)
    return drug


def serialize_plan(db, plan):
    prescriptions = db.scalars(select(Prescription).where(Prescription.plan_id == plan.id).order_by(Prescription.id)).all()
    return {"id": plan.id, "patient_id": plan.patient_id, "doctor_id": plan.doctor_id,
            "title": plan.title, "instructions": plan.instructions, "version": plan.version,
            "status": plan.status, "created_at": plan.created_at,
            "confirmed_at": plan.confirmed_at, "confirmed_by": plan.confirmed_by,
            "prescriptions": [{"drug_id": p.drug_id, "regimen": p.regimen, "drug": p.drug_snapshot} for p in prescriptions]}


@router.get("/patients/{patient_id}/plans")
def plans(patient_id: int, user: Auth, db: DB):
    patient_access(db, user, patient_id)
    query = select(TreatmentPlan).where(TreatmentPlan.patient_id == patient_id)
    if user.role == "patient":
        query = query.where(TreatmentPlan.confirmed_at.is_not(None))
    return [serialize_plan(db, p) for p in db.scalars(query.order_by(TreatmentPlan.version.desc()))]


@router.post("/patients/{patient_id}/plans", status_code=201)
def create_plan(patient_id: int, data: PlanInput, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id, lock=True)
    version = (db.scalar(select(func.max(TreatmentPlan.version)).where(TreatmentPlan.patient_id == patient_id)) or 0) + 1
    drug_rows = []
    for item in data.prescriptions:
        drug = db.get(Drug, item.drug_id)
        if not drug or drug.status != "verified" or not drug.registered_rf or not drug.verified_at:
            raise HTTPException(409, "В назначении допустимы только проверенные врачом записи ГРЛС")
        drug_rows.append((item, drug))
    plan = TreatmentPlan(patient_id=patient_id, doctor_id=user.id, version=version,
                         title=data.title, instructions=data.instructions)
    db.add(plan)
    db.flush()
    for item, drug in drug_rows:
        db.add(Prescription(plan_id=plan.id, drug_id=drug.id, regimen=item.regimen, drug_snapshot=drug_data(drug)))
    audit(db, user.id, patient_id, "treatment_plan", plan.id, "draft_created", {"version": version})
    db.commit()
    return serialize_plan(db, plan)


@router.post("/patients/{patient_id}/plans/{plan_id}/confirm")
def confirm_plan(patient_id: int, plan_id: int, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id, lock=True)
    plan = db.get(TreatmentPlan, plan_id)
    if not plan or plan.patient_id != patient_id or plan.doctor_id != user.id:
        raise HTTPException(404, "План не найден")
    if plan.status != "draft":
        raise HTTPException(409, "Подтвердить можно только черновик")
    for prescription in db.scalars(select(Prescription).where(Prescription.plan_id == plan.id)):
        drug = db.get(Drug, prescription.drug_id)
        if drug.status != "verified" or not drug.registered_rf:
            raise HTTPException(409, "Справочные сведения требуют проверки")
    for previous in db.scalars(select(TreatmentPlan).where(TreatmentPlan.patient_id == patient_id, TreatmentPlan.status == "active")):
        if previous.version > plan.version:
            raise HTTPException(409, "Уже действует более новая версия плана")
        previous.status = "superseded"
        audit(db, user.id, patient_id, "treatment_plan", previous.id, "superseded", {"replacement": plan.id})
    plan.status = "active"
    plan.confirmed_by, plan.confirmed_at = user.id, datetime.now(timezone.utc)
    audit(db, user.id, patient_id, "treatment_plan", plan.id, "confirmed", {"version": plan.version})
    db.commit()
    return serialize_plan(db, plan)


@router.get("/patients/{patient_id}/audit")
def history(patient_id: int, user: Auth, db: DB):
    require_doctor(user)
    patient_access(db, user, patient_id)
    return db.scalars(select(AuditEvent).where(AuditEvent.patient_id == patient_id).order_by(AuditEvent.id.desc())).all()
