import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.backend.core.security import (Auth, DB, digest, patient_access, public_user,
                                       require_doctor, require_patient)
from app.backend.models.user import User
from app.backend.models.clinical import Invitation
from app.backend.schemas.clinical import Invite, AcceptInvite
from app.backend.services.workflows import audit
from app.backend.services.mail import send_invitation

router = APIRouter(prefix="/api", tags=["Patients"])


@router.post("/invitations", status_code=201)
def invite(data: Invite, user: Auth, db: DB):
    require_doctor(user)
    token = secrets.token_urlsafe(32)
    invitation = Invitation(doctor_id=user.id, email=str(data.email).lower(),
                            token_hash=digest(token), expires_at=datetime.now(timezone.utc) + timedelta(days=2))
    db.add(invitation)
    db.flush()
    send_invitation(invitation.email, token)
    invitation.delivery_status = "sent"
    db.commit()
    return {"id": invitation.id, "expires_at": invitation.expires_at,
            "delivery_status": "sent"}


@router.post("/invitations/accept")
def accept(data: AcceptInvite, user: Auth, db: DB):
    require_patient(user)
    patient = patient_access(db, user, user.id, lock=True)
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest(data.token)).with_for_update())
    if invitation and invitation.email == patient.email and invitation.accepted_by == patient.id and patient.doctor_id == invitation.doctor_id:
        return public_user(patient)
    if not invitation or invitation.email != patient.email or invitation.accepted_by is not None or (
        invitation.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
    ):
        raise HTTPException(400, "Приглашение недействительно или истекло")
    if patient.doctor_id:
        raise HTTPException(409, "Ведущий врач уже назначен; смена требует отдельной процедуры")
    patient.doctor_id = invitation.doctor_id
    invitation.accepted_by = patient.id
    audit(db, user.id, patient.id, "invitation", invitation.id, "accepted")
    db.commit()
    return public_user(patient)


@router.get("/patients")
def patients(user: Auth, db: DB):
    require_doctor(user)
    return [public_user(p) for p in db.scalars(select(User).where(User.role == "patient", User.doctor_id == user.id).order_by(User.id))]


@router.get("/patients/{patient_id}")
def patient(patient_id: int, user: Auth, db: DB):
    return public_user(patient_access(db, user, patient_id))
