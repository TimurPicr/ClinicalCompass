import os
import hmac
import hashlib
import secrets

from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field as PField
from sqlmodel import SQLModel, Field, Session, create_engine, select


# ================= DATABASE =================

engine = create_engine(
    "sqlite:///database.db",
    connect_args={"check_same_thread": False}
)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str
    doctor_id: int | None = Field(default=None, foreign_key="user.id")


class Treatment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    doctor_id: int = Field(foreign_key="user.id")
    patient_id: int = Field(foreign_key="user.id")
    title: str
    instructions: str
    status: str = "active"


class CheckIn(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    treatment_id: int = Field(foreign_key="treatment.id")
    taken: bool
    mood: int
    note: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    sender_id: int = Field(foreign_key="user.id")
    receiver_id: int = Field(foreign_key="user.id")
    text: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ================= SCHEMAS =================

class PatientCreate(BaseModel):
    username: str
    password: str = PField(min_length=8)


class TreatmentCreate(BaseModel):
    patient_id: int
    title: str
    instructions: str


class CheckInCreate(BaseModel):
    taken: bool
    mood: int = PField(ge=1, le=10)
    note: str = ""


class MessageCreate(BaseModel):
    receiver_id: int
    text: str


# ================= AUTH =================

security = HTTPBasic()


def hash_password(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 300_000
    )
    return f"{salt}:{digest.hex()}"


def get_db():
    with Session(engine) as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def current_user(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
    db: DB
):
    user = db.exec(
        select(User).where(User.username == credentials.username)
    ).first()

    if user:
        salt = user.password_hash.split(":")[0]
        valid = hmac.compare_digest(
            user.password_hash,
            hash_password(credentials.password, salt)
        )
        if valid:
            return user

    raise HTTPException(
        401, "Invalid credentials",
        headers={"WWW-Authenticate": "Basic"}
    )


Auth = Annotated[User, Depends(current_user)]


def require_doctor(user):
    if user.role != "doctor":
        raise HTTPException(403, "Doctor only")


def get_treatment(treatment_id, user, db):
    treatment = db.get(Treatment, treatment_id)

    if not treatment or not (
        (user.role == "doctor" and treatment.doctor_id == user.id)
        or
        (user.role == "patient" and treatment.patient_id == user.id)
    ):
        raise HTTPException(404, "Treatment not found")

    return treatment


def check_contact(user, other_id, db):
    other = db.get(User, other_id)

    allowed = other and (
        (user.role == "doctor"
         and other.role == "patient"
         and other.doctor_id == user.id)
        or
        (user.role == "patient"
         and other.role == "doctor"
         and user.doctor_id == other.id)
    )

    if not allowed:
        raise HTTPException(403, "Contact not allowed")


# ================= APP =================

@asynccontextmanager
async def lifespan(app):
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        if not db.exec(select(User).where(User.role == "doctor")).first():
            db.add(User(
                username=os.getenv("DOCTOR_USER", "doctor"),
                password_hash=hash_password(
                    os.getenv("DOCTOR_PASSWORD", "doctor123")
                ),
                role="doctor"
            ))
            db.commit()

    yield


app = FastAPI(title="Clinical Compass MVP", lifespan=lifespan)


# ================= CABINETS =================

@app.get("/me")
def me(user: Auth):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "doctor_id": user.doctor_id
    }


@app.post("/patients")
def create_patient(data: PatientCreate, user: Auth, db: DB):
    require_doctor(user)

    if db.exec(select(User).where(User.username == data.username)).first():
        raise HTTPException(409, "Username already exists")

    patient = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role="patient",
        doctor_id=user.id
    )

    db.add(patient)
    db.commit()
    db.refresh(patient)

    return {"id": patient.id, "username": patient.username}


@app.get("/patients")
def patients(user: Auth, db: DB):
    require_doctor(user)

    users = db.exec(
        select(User).where(User.doctor_id == user.id)
    ).all()

    return [{"id": p.id, "username": p.username} for p in users]


# ================= TREATMENTS =================

@app.post("/treatments")
def create_treatment(data: TreatmentCreate, user: Auth, db: DB):
    require_doctor(user)

    patient = db.get(User, data.patient_id)

    if not patient or patient.doctor_id != user.id:
        raise HTTPException(403, "Patient not assigned to you")

    treatment = Treatment(
        doctor_id=user.id,
        **data.model_dump()
    )

    db.add(treatment)
    db.commit()
    db.refresh(treatment)

    return treatment


@app.get("/treatments")
def treatments(user: Auth, db: DB):
    condition = (
        Treatment.doctor_id == user.id
        if user.role == "doctor"
        else Treatment.patient_id == user.id
    )

    return db.exec(select(Treatment).where(condition)).all()


@app.patch("/treatments/{treatment_id}/complete")
def complete_treatment(treatment_id: int, user: Auth, db: DB):
    require_doctor(user)

    treatment = get_treatment(treatment_id, user, db)
    treatment.status = "completed"

    db.add(treatment)
    db.commit()

    return {"status": "completed"}


# ================= TRACKER =================

@app.post("/treatments/{treatment_id}/checkins")
def add_checkin(
    treatment_id: int,
    data: CheckInCreate,
    user: Auth,
    db: DB
):
    treatment = get_treatment(treatment_id, user, db)

    if user.role != "patient" or treatment.status != "active":
        raise HTTPException(403, "Cannot submit check-in")

    checkin = CheckIn(
        treatment_id=treatment_id,
        **data.model_dump()
    )

    db.add(checkin)
    db.commit()
    db.refresh(checkin)

    return checkin


@app.get("/treatments/{treatment_id}/checkins")
def get_checkins(treatment_id: int, user: Auth, db: DB):
    get_treatment(treatment_id, user, db)

    return db.exec(
        select(CheckIn)
        .where(CheckIn.treatment_id == treatment_id)
        .order_by(CheckIn.created_at)
    ).all()


# ================= CHAT =================

@app.post("/messages")
def send_message(data: MessageCreate, user: Auth, db: DB):
    check_contact(user, data.receiver_id, db)

    message = Message(
        sender_id=user.id,
        **data.model_dump()
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


@app.get("/messages/{other_id}")
def get_messages(other_id: int, user: Auth, db: DB):
    check_contact(user, other_id, db)

    return db.exec(
        select(Message)
        .where(
            ((Message.sender_id == user.id) &
             (Message.receiver_id == other_id))
            |
            ((Message.sender_id == other_id) &
             (Message.receiver_id == user.id))
        )
        .order_by(Message.created_at)
    ).all()