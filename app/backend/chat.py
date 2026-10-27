"""One persisted room per patient. Run one ASGI process for live broadcasts."""
from collections import defaultdict
import json
import secrets
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from app.backend.auth import accessible_patient, current_user, digest, doctor_user, user_from_token
from app.backend.clinical_common import aware
from app.backend.config import settings
from app.backend.documents import save_upload, stored_path
from database.connection import get_db, SessionLocal
from database.models import AuthSession, ChatAttachment, Message, Patient, User

router = APIRouter(tags=['Чат'])
rooms: dict[int, set[WebSocket]] = defaultdict(set)

class MessageInput(BaseModel):
    text: str = Field(default='', max_length=5000)
    attachment_id: int | None = None
    @model_validator(mode='after')
    def nonempty(self):
        self.text = self.text.strip()
        if not self.text and self.attachment_id is None:
            raise ValueError('Напишите сообщение или добавьте файл')
        return self

def _message_view(row, sender, file):
    return dict(id=row.id, patient_id=row.patient_id, sender_id=row.sender_id,
                sender_name=sender.name, text=row.text, created_at=aware(row.created_at).isoformat(),
                attachment=dict(id=file.id,name=file.name,mime=file.mime,size=file.size,
                                url=f'/api/chat/attachments/{file.id}') if file else None)

def message_view(db, row):
    sender = db.get(User, row.sender_id)
    file = db.get(ChatAttachment, row.attachment_id) if row.attachment_id else None
    return _message_view(row, sender, file)

def remove_socket(patient_id, socket):
    members = rooms.get(patient_id)
    if members is not None:
        members.discard(socket)
        if not members:
            rooms.pop(patient_id, None)

async def broadcast(patient_id, payload):
    for socket in tuple(rooms.get(patient_id, ())):
        try:
            # Logout, expiry or changed room access must also revoke receivers.
            with SessionLocal() as db:
                recipient = user_from_token(db, socket.cookies.get('cc_session'))
                if not recipient:
                    await socket.close(code=4401)
                    remove_socket(patient_id, socket)
                    continue
                try:
                    accessible_patient(db, recipient, patient_id)
                except HTTPException:
                    await socket.close(code=4404)
                    remove_socket(patient_id, socket)
                    continue
            await socket.send_json(payload)
        except Exception:
            remove_socket(patient_id, socket)

@router.get('/api/chats')
def inbox(user=Depends(doctor_user), db=Depends(get_db)):
    latest = (select(Message.id).where(Message.patient_id == Patient.id)
              .order_by(Message.created_at.desc(), Message.id.desc()).limit(1)
              .correlate(Patient).scalar_subquery())
    sender = aliased(User)
    rows = db.execute(select(Patient.id, User.name, Message, sender, ChatAttachment)
                      .join(User, User.id == Patient.id)
                      .outerjoin(Message, Message.id == latest)
                      .outerjoin(sender, sender.id == Message.sender_id)
                      .outerjoin(ChatAttachment, ChatAttachment.id == Message.attachment_id)
                      .where(Patient.doctor_id == user.id)
                      .order_by(Message.created_at.desc().nullslast(), Message.id.desc().nullslast(), Patient.id))
    return [dict(patient_id=patient_id, patient_name=name,
                 last_message=_message_view(message, author, attachment) if message else None)
            for patient_id, name, message, author, attachment in rows]

def save_message(db, user, patient_id, data):
    accessible_patient(db, user, patient_id)
    if data.attachment_id is not None:
        file = db.scalar(select(ChatAttachment).where(ChatAttachment.id == data.attachment_id).with_for_update())
        if not file or file.patient_id != patient_id or file.uploader_id != user.id:
            raise HTTPException(404, 'Вложение не найдено')
        if db.scalar(select(Message.id).where(Message.attachment_id == file.id)):
            raise HTTPException(409, 'Вложение уже отправлено')
    message = Message(patient_id=patient_id,sender_id=user.id,text=data.text,attachment_id=data.attachment_id)
    db.add(message)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Вложение уже отправлено')
    return message_view(db, message)

@router.get('/api/patients/{patient_id}/chat')
def history(patient_id: int, before: int | None = None, user=Depends(current_user), db=Depends(get_db)):
    accessible_patient(db, user, patient_id)
    query = select(Message).where(Message.patient_id == patient_id)
    if before:
        query = query.where(Message.id < before)
    rows = db.scalars(query.order_by(Message.id.desc()).limit(100)).all()
    return [message_view(db,m) for m in reversed(rows)]

@router.post('/api/patients/{patient_id}/chat')
async def post_message(patient_id: int, data: MessageInput, user=Depends(current_user), db=Depends(get_db)):
    result = save_message(db,user,patient_id,data)
    await broadcast(patient_id, result)
    return result

@router.post('/api/patients/{patient_id}/chat/attachments')
async def upload(patient_id: int, file: UploadFile = File(...), user=Depends(current_user), db=Depends(get_db)):
    accessible_patient(db,user,patient_id)
    data = await save_upload(file)
    data.pop('checksum')
    row = ChatAttachment(patient_id=patient_id,uploader_id=user.id,**data)
    db.add(row)
    db.commit()
    return {'id':row.id,'name':row.name,'mime':row.mime,'size':row.size}

@router.get('/api/chat/attachments/{attachment_id}')
def download(attachment_id: int,user=Depends(current_user),db=Depends(get_db)):
    file=db.get(ChatAttachment,attachment_id)
    if not file:
        raise HTTPException(404,'Файл не найден')
    accessible_patient(db,user,file.patient_id)
    return FileResponse(stored_path(file.storage_name),media_type=file.mime,filename=file.name,
                        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

@router.websocket('/ws/chat/{patient_id}')
async def websocket_chat(websocket: WebSocket, patient_id: int):
    token = websocket.cookies.get('cc_session')
    with SessionLocal() as db:
        user=user_from_token(db,token)
        auth=db.get(AuthSession,digest(token)) if user else None
        origin=websocket.headers.get('origin','')
        if (not user or origin not in settings.origins or not auth
                or not secrets.compare_digest(auth.csrf,websocket.query_params.get('csrf',''))):
            await websocket.close(code=4403)
            return
        try:
            accessible_patient(db,user,patient_id)
        except HTTPException:
            await websocket.close(code=4404)
            return
        user_id = user.id
    await websocket.accept()
    rooms[patient_id].add(websocket)
    try:
        while True:
            event = await websocket.receive()
            if event['type'] == 'websocket.disconnect':
                break
            raw = event.get('text')
            if raw is None:
                await websocket.close(code=1003)
                break
            if len(raw) > 15000:
                await websocket.close(code=1009)
                break
            with SessionLocal() as db:
                user=user_from_token(db,token)
                if not user or user.id != user_id:
                    await websocket.close(code=4401)
                    break
                try:
                    accessible_patient(db, user, patient_id)
                except HTTPException:
                    await websocket.close(code=4404)
                    break
                try:
                    data=json.loads(raw)
                    if isinstance(data, dict) and data.get('type') == 'ping':
                        await websocket.send_json({'type':'pong'})
                        continue
                    result=save_message(db,user,patient_id,MessageInput.model_validate(data))
                except (ValueError, HTTPException) as error:
                    await websocket.send_json({'error':str(getattr(error,'detail','Некорректное сообщение'))})
                    continue
            await broadcast(patient_id,result)
    except WebSocketDisconnect:
        pass
    finally:
        remove_socket(patient_id, websocket)
