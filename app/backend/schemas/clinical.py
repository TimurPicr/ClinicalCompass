from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlparse

from app.backend.core.time import report_date

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator
from app.backend.schemas.questionnaire import QuestionnaireSubmission

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Register(Login):
    full_name: Title
    password: str = Field(min_length=12, max_length=128)


class Invite(Input):
    email: EmailStr


class AcceptInvite(Input):
    token: str = Field(min_length=32, max_length=128)


class UrgentRequest(Input):
    event_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class Review(Input):
    status: Literal["accepted", "rejected"]
    comment: Text


class Comment(Input):
    comment: Text


class PrescriptionInput(Input):
    drug_id: int = Field(gt=0)
    regimen: Text


class PlanInput(Input):
    title: Title
    instructions: Text
    prescriptions: list[PrescriptionInput] = Field(default_factory=list, max_length=30)


class DrugInput(Input):
    name: Title
    indications: Text
    contraindications: Text
    dosing: Text
    source_url: str = Field(max_length=2048)
    registration_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

    @field_validator("source_url")
    @classmethod
    def grls_source(cls, value):
        url = urlparse(value)
        if url.scheme != "https" or not url.hostname or not (
            url.hostname == "grls.rosminzdrav.ru" or url.hostname.endswith(".grls.rosminzdrav.ru")
        ) or url.username or url.password:
            raise ValueError("Нужна HTTPS-ссылка на документ ГРЛС")
        if not url.path or url.path == "/":
            raise ValueError("Укажите ссылку на конкретную запись ГРЛС")
        return value


class DrugVerification(Input):
    registered_rf: Literal[True]
    comment: Text


class ReportInput(Input):
    plan_id: int = Field(gt=0)
    report_date: date
    status: Literal["completed", "missed", "partial"]
    note: str = Field(default="", max_length=5000)

    @field_validator("report_date")
    @classmethod
    def not_future(cls, value):
        if value > report_date():
            raise ValueError("Дата не может быть в будущем")
        return value


class AdverseInput(Input):
    plan_id: int | None = Field(default=None, gt=0)
    onset_date: date
    description: Text

    @field_validator("onset_date")
    @classmethod
    def not_future(cls, value):
        if value > report_date():
            raise ValueError("Дата не может быть в будущем")
        return value


class MessageInput(Input):
    text: Text


class RagQuestion(Input):
    question: Text


class DiaryInput(QuestionnaireSubmission):
    model_config = ConfigDict(extra="forbid")
    entry_date: date
    text: str = Field(default="", max_length=10000)

    @field_validator("entry_date")
    @classmethod
    def not_future(cls, value):
        if value > report_date():
            raise ValueError("Нельзя заполнять будущие дни")
        return value
