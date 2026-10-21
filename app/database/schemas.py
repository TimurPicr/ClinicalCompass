from sqlmodel import SQLModel, Field, Session, create_engine, select
from datetime import datetime, timezone

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