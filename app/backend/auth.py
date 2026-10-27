"""Cookie sessions, single-use invitations, and developer-issued access recovery."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database.connection import get_db
from database.models import AuthSession, Invitation, Patient, ResetToken, User, utcnow
from app.backend.config import settings

router = APIRouter(prefix='/api/auth', tags=['Авторизация'])
hasher = PasswordHasher()

def digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()

def aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def hash_password(password: str) -> str:
    return hasher.hash(password)

def user_from_token(db: Session, token: str | None):
    if not token:
        return None
    session = db.get(AuthSession, digest(token))
    if not session or aware(session.expires_at) <= utcnow():
        return None
    return db.get(User, session.user_id)

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, request.cookies.get('cc_session'))
    if user is None:
        raise HTTPException(401, 'Войдите в приложение')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        session = db.get(AuthSession, digest(request.cookies['cc_session']))
        if not secrets.compare_digest(session.csrf, request.headers.get('X-CSRF-Token', '')):
            raise HTTPException(403, 'Недействительный CSRF-токен. Обновите страницу')
    return user

def doctor_user(user: User = Depends(current_user)) -> User:
    if user.role != 'doctor':
        raise HTTPException(403, 'Действие доступно только врачу')
    return user

def accessible_patient(db: Session, user: User, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient or not (user.id == patient.id or (user.role == 'doctor' and user.id == patient.doctor_id)):
        raise HTTPException(404, 'Пациент не найден')
    return patient

def public_user(user: User):
    return dict(id=user.id, email=user.email, name=user.name, role=user.role,
                timezone=user.timezone, patient_id=user.id if user.role == 'patient' else None)

def create_session(db, user, response):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=settings.session_days)
    db.add(AuthSession(id=digest(token), user_id=user.id, csrf=csrf, expires_at=expires))
    db.commit()
    options = dict(secure=settings.cookie_secure, samesite='lax', path='/', max_age=settings.session_days * 86400)
    response.set_cookie('cc_session', token, httponly=True, **options)
    response.set_cookie('cc_csrf', csrf, httponly=False, **options)

class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)

class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=256)

class RegisterInput(PasswordInput):
    token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=2, max_length=160)
    timezone: str = 'Europe/Moscow'
    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('Укажите имя не короче двух символов')
        return value

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Неизвестный часовой пояс')
        return value

class ResetInput(PasswordInput):
    token: str = Field(min_length=20, max_length=200)

class InviteInput(BaseModel):
    email: EmailStr
    expires_hours: int = Field(default=48, ge=1, le=168)

@router.get('/csrf')
def csrf_token(request: Request, response: Response, db: Session = Depends(get_db)):
    session_token = request.cookies.get('cc_session')
    session = db.get(AuthSession, digest(session_token)) if session_token else None
    if session and aware(session.expires_at) > utcnow():
        # Recover a missing/stale readable cookie without rotating the active
        # session's token or weakening mutation/WebSocket CSRF checks.
        token = session.csrf
    else:
        token = request.cookies.get('cc_csrf') or secrets.token_urlsafe(32)
    response.set_cookie('cc_csrf', token, secure=settings.cookie_secure, httponly=False, samesite='lax')
    return {'csrf_token': token}

@router.get('/me')
def me(user: User = Depends(current_user)):
    return public_user(user)

@router.post('/login')
def login(data: LoginInput, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = False
    try:
        # A dummy hash prevents a fast unknown-account path.
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, data.password)
    except (VerificationError, InvalidHashError):
        pass
    if not user or not valid:
        raise HTTPException(401, 'Неверный email или пароль')
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    create_session(db, user, response)
    return public_user(user)

@router.post('/logout')
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.id == digest(request.cookies['cc_session'])))
    db.commit()
    response.delete_cookie('cc_session', path='/')
    response.delete_cookie('cc_csrf', path='/')
    return {'ok': True}

@router.post('/invitations')
def invite(data: InviteInput, user: User = Depends(doctor_user), db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, 'Этот email уже зарегистрирован')
    token = secrets.token_urlsafe(32)
    invitation = Invitation(doctor_id=user.id, email=email, token_hash=digest(token), expires_at=utcnow() + timedelta(hours=data.expires_hours))
    db.add(invitation)
    db.commit()
    return {'id': invitation.id, 'email': email, 'expires_at': invitation.expires_at,
            'link': f'{settings.public_url}/?invite={token}'}

@router.get('/invitations')
def invitations(user: User = Depends(doctor_user), db: Session = Depends(get_db)):
    return [{'id': i.id, 'email': i.email, 'expires_at': i.expires_at, 'used_at': i.used_at} for i in db.scalars(select(Invitation).where(Invitation.doctor_id == user.id).order_by(Invitation.id.desc())).all()]

@router.get('/invitations/inspect')
def inspect_invite(token: str, db: Session = Depends(get_db)):
    invite = db.scalar(select(Invitation).where(Invitation.token_hash == digest(token)))
    if not invite or invite.used_at or aware(invite.expires_at) <= utcnow():
        raise HTTPException(400, 'Приглашение истекло или уже использовано')
    doctor = db.get(User, invite.doctor_id)
    return {'email': invite.email, 'doctor': doctor.name, 'expires_at': invite.expires_at}

@router.post('/register')
def register(data: RegisterInput, response: Response, db: Session = Depends(get_db)):
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == digest(data.token)).with_for_update())
    if not invitation or invitation.used_at or aware(invitation.expires_at) <= utcnow():
        raise HTTPException(400, 'Приглашение истекло или уже использовано')
    user = User(email=invitation.email, name=data.name.strip(), role='patient', timezone=data.timezone, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.flush()
        db.add(Patient(id=user.id, doctor_id=invitation.doctor_id))
        invitation.used_at = utcnow()
        create_session(db, user, response)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Этот email уже зарегистрирован')
    return public_user(user)

@router.post('/reset')
def reset(data: ResetInput, response: Response, db: Session = Depends(get_db)):
    item = db.scalar(select(ResetToken).where(ResetToken.token_hash == digest(data.token)).with_for_update())
    if not item or item.used_at or aware(item.expires_at) <= utcnow():
        raise HTTPException(400, 'Ссылка восстановления истекла или уже использована')
    user = db.get(User, item.user_id)
    user.password_hash = hash_password(data.password)
    item.used_at = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    create_session(db, user, response)
    return public_user(user)

DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
