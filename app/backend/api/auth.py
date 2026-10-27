import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, Response, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.backend.core.config import settings
from app.backend.core.security import Auth, DB, DUMMY_HASH, digest, passwords, public_user
from app.backend.models.user import User
from app.backend.models.clinical import AuthSession
from app.backend.schemas.clinical import Register, Login

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register", status_code=201)
def register(data: Register, db: DB):
    user = User(email=str(data.email).lower(), full_name=data.full_name,
                password_hash=passwords.hash(data.password), role="patient")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email уже зарегистрирован") from None
    db.refresh(user)
    return public_user(user)


@router.post("/login")
def login(data: Login, response: Response, db: DB):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Неверный email или пароль")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    token_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_id=token_id, csrf_hash=digest(csrf), expires_at=expires))
    db.commit()
    token = jwt.encode({"sub": str(user.id), "jti": token_id, "iat": now, "exp": expires,
                        "iss": "clinical-compass", "aud": "clinical-compass-web"},
                       settings.jwt_secret_key, algorithm="HS256")
    response.set_cookie("cc_session", token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.access_token_expire_minutes * 60, path="/")
    response.set_cookie("cc_csrf", csrf, httponly=False, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.access_token_expire_minutes * 60, path="/")
    response.headers["Cache-Control"] = "no-store"
    return public_user(user)


@router.get("/me")
def me(user: Auth):
    return public_user(user)


@router.post("/logout", status_code=204)
def logout(user: Auth, db: DB, response: Response, request: Request):
    # Revoke the current session only, leaving other devices signed in.
    request.state.auth_session.revoked = True
    db.commit()
    response.delete_cookie("cc_session", path="/")
    response.delete_cookie("cc_csrf", path="/")
