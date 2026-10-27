"""JWT in a revocable HttpOnly cookie, CSRF bound to the server session."""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.core.config import settings
from app.backend.models.user import User
from app.backend.models.clinical import AuthSession
from app.database.connection import get_db

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("synthetic-timing-equalization-password")
DB = Annotated[Session, Depends(get_db)]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def current_user(request: Request, db: DB) -> User:
    try:
        payload = jwt.decode(
            request.cookies.get("cc_session", ""), settings.jwt_secret_key,
            algorithms=["HS256"], issuer="clinical-compass", audience="clinical-compass-web",
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        session = db.scalar(select(AuthSession).where(AuthSession.token_id == payload["jti"]))
        if not session or session.revoked or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise ValueError("Inactive session")
        user = db.get(User, int(payload["sub"]))
        if not user or session.user_id != user.id:
            raise ValueError("Invalid subject")
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Войдите в систему") from None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not hmac.compare_digest(digest(csrf), session.csrf_hash):
            raise HTTPException(403, "Недействительный CSRF-токен")
    request.state.auth_session = session
    return user


Auth = Annotated[User, Depends(current_user)]


def require_doctor(user: User):
    if user.role != "doctor":
        raise HTTPException(403, "Доступно только врачу")


def require_patient(user: User):
    if user.role != "patient":
        raise HTTPException(403, "Доступно только пациенту")


def patient_access(db: Session, user: User, patient_id: int, *, lock=False) -> User:
    statement = select(User).where(User.id == patient_id, User.role == "patient")
    if lock:
        statement = statement.with_for_update()
    patient = db.scalar(statement)
    if not patient or not (
        (user.role == "patient" and user.id == patient.id)
        or (user.role == "doctor" and patient.doctor_id == user.id)
    ):
        raise HTTPException(404, "Пациент не найден")
    return patient


def public_user(user: User):
    return {"id": user.id, "email": user.email, "full_name": user.full_name,
            "role": user.role, "doctor_id": user.doctor_id}
