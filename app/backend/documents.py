"""Private originals, local PDF/OCR extraction and doctor-reviewed proposals."""
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select

from app.backend.ai.ollama import UNTRUSTED_INSTRUCTIONS
from app.backend.ai.queue import enqueue
from app.backend.ai.schemas import DocumentResult
from app.backend.auth import accessible_patient, current_user, doctor_user
from app.backend.config import settings
from database.connection import get_db
from database.models import Audit, Document

router = APIRouter(prefix='/api', tags=['documents'])
MIMES = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
         '.png': 'image/png', '.webp': 'image/webp'}


def stored_path(storage_name):
    if not re.fullmatch(r'[a-f0-9]{32}\.(pdf|jpg|jpeg|png|webp|txt)', storage_name):
        raise HTTPException(404, 'Файл не найден')
    root = Path(settings.upload_dir).resolve()
    path = (root / storage_name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, 'Файл не найден')
    return path


def validate_file(data, extension):
    mime = MIMES.get(extension)
    if mime is None:
        raise HTTPException(415, 'Разрешены PDF, JPEG, PNG и WebP')
    if not data:
        raise HTTPException(422, 'Файл пуст')
    if extension == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise HTTPException(415, 'Содержимое файла не соответствует PDF')
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise HTTPException(422, 'PDF защищён паролем')
            if len(reader.pages) > 60:
                raise HTTPException(422, 'Допускается не более 60 страниц')
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'Не удалось прочитать PDF')
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}[extension]
                if image.format != expected or image.width * image.height > 30_000_000:
                    raise HTTPException(415, 'Неверный формат изображения или более 30 мегапикселей')
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError):
            raise HTTPException(422, 'Изображение повреждено или слишком велико')
    return mime


async def save_upload(file: UploadFile):
    extension = Path(file.filename or '').suffix.lower()
    maximum = settings.max_upload_mb * 1024 * 1024
    content = bytearray()
    while chunk := await file.read(64 * 1024):
        content.extend(chunk)
        if len(content) > maximum:
            raise HTTPException(413, f'Размер файла превышает {settings.max_upload_mb} МБ')
    mime = validate_file(bytes(content), extension)
    storage_name = uuid.uuid4().hex + extension
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / storage_name
    with path.open('xb') as output:
        output.write(content)
    path.chmod(0o600)
    return {'name': Path(file.filename or 'document').name[:255], 'storage_name': storage_name,
            'mime': mime, 'size': len(content), 'checksum': hashlib.sha256(content).hexdigest()}


def ocr_image(path):
    if not shutil.which('tesseract'):
        raise RuntimeError('Для OCR установите tesseract и языки rus+eng (см. README)')
    result = subprocess.run(['tesseract', str(path), 'stdout', '-l', 'rus+eng'],
                            capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError('OCR не выполнен: проверьте tesseract и языки rus+eng')
    return result.stdout.strip()


def extract_pages(path, mime):
    pages = []
    if mime != 'application/pdf':
        pages.append({'page': 1, 'text': ocr_image(path), 'method': 'ocr'})
    else:
        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 60:
            raise ValueError('PDF зашифрован или содержит более 60 страниц')
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or '').strip()
            method = 'pdf_text'
            if len(text) < 30:
                if not shutil.which('pdftoppm'):
                    raise RuntimeError('Для сканированного PDF установите poppler (pdftoppm)')
                with tempfile.TemporaryDirectory(prefix='compass-ocr-') as temporary:
                    output = Path(temporary) / 'page'
                    result = subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number),
                                             '-r', '140', '-scale-to', '2500', '-singlefile', '-png', str(path), str(output)],
                                            capture_output=True, timeout=90, check=False)
                    if result.returncode:
                        raise RuntimeError(f'Не удалось подготовить страницу {number} для OCR')
                    text = ocr_image(output.with_suffix('.png'))
                method = 'ocr'
            pages.append({'page': number, 'text': text[:50_000], 'method': method})
    if not any(page['text'] for page in pages):
        raise ValueError('Не удалось извлечь текст')
    if sum(len(page['text']) for page in pages) > 500_000:
        raise ValueError('Документ слишком велик для извлечения (500 000 символов)')
    return pages


def process_document(db, document_id, client):
    document = db.get(Document, document_id)
    if not document:
        raise ValueError('Документ не найден')
    if document.status == 'processed':
        # A retried/stale queue row must never replace reviewed proposals.
        return
    pages = document.extraction.get('pages') or extract_pages(stored_path(document.storage_name), document.mime)
    proposals = []
    # One page per request keeps provenance exact and bounded context on 18GB Macs.
    for page in pages:
        if not page['text'].strip():
            continue
        for start in range(0, len(page['text']), 10_000):
            fragment = page['text'][start:start + 10_000]
            result = client.structured(DocumentResult, UNTRUSTED_INSTRUCTIONS +
                'Извлеки только сведения, явно написанные в документе. Не ставь диагноз. '
                'Для каждого предложения укажи исходную страницу и точную дословную цитату. '
                'Если сведений нет, верни пустой список. Данные пока не подтверждены врачом.',
                {'page': page['page'], 'text': fragment})
            for proposal in result.proposals:
                if proposal.page != page['page'] or proposal.quote not in fragment:
                    raise ValueError('Извлечённые сведения не имеют точного подтверждения на исходной странице')
                proposals.append(proposal.model_dump())
    document.extracted_text = '\n\n'.join(f"[Страница {page['page']}]\n{page['text']}" for page in pages)
    document.extraction = {'pages': pages, 'proposals': proposals, 'review_status': 'unconfirmed',
                           'notice': 'Предложения не изменяют медицинскую карту. Врач переносит проверенные сведения вручную.'}
    document.status = 'processed'


def document_view(document, include_text=False):
    extraction = {key: value for key, value in document.extraction.items() if key != 'pages'}
    if include_text:
        extraction['pages'] = document.extraction.get('pages', [])
    return {key: getattr(document, key) for key in ('id', 'name', 'mime', 'size', 'status', 'created_at')} | {'extraction': extraction}


@router.get('/patients/{patient_id}/documents')
def list_documents(patient_id: int, user=Depends(current_user), db=Depends(get_db)):
    accessible_patient(db, user, patient_id)
    return [document_view(document, True) for document in db.scalars(select(Document).where(
        Document.patient_id == patient_id).order_by(Document.created_at.desc()))]


@router.post('/patients/{patient_id}/documents', status_code=201)
async def upload_document(patient_id: int, file: UploadFile = File(...), user=Depends(current_user), db=Depends(get_db)):
    accessible_patient(db, user, patient_id)
    saved = await save_upload(file)
    document = Document(patient_id=patient_id, uploader_id=user.id, **saved)
    try:
        db.add(document)
        db.flush()
        enqueue(db, patient_id, 'document', {'document_id': document.id}, f'document:{document.id}')
        db.commit()
    except Exception:
        db.rollback()
        (Path(settings.upload_dir) / saved['storage_name']).unlink(missing_ok=True)
        raise
    return document_view(document)


@router.get('/documents/{document_id}/download')
def download_document(document_id: int, user=Depends(current_user), db=Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, 'Документ не найден')
    accessible_patient(db, user, document.patient_id)
    return FileResponse(stored_path(document.storage_name), media_type=document.mime, filename=document.name,
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})


class Review(BaseModel):
    status: Literal['confirmed', 'rejected']
    comment: str = Field(default='', max_length=3000)


@router.post('/documents/{document_id}/review')
def review_document(document_id: int, data: Review, user=Depends(doctor_user), db=Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(404, 'Документ не найден')
    accessible_patient(db, user, document.patient_id)
    if document.status != 'processed':
        raise HTTPException(409, 'Извлечение документа ещё не завершено')
    previous = dict(document.extraction)
    from app.backend.ai.queue import utcnow
    document.extraction = {**previous, 'review_status': data.status, 'review_comment': data.comment,
                           'reviewed_by': user.id, 'reviewed_at': utcnow().isoformat()}
    db.add(Audit(patient_id=document.patient_id, actor_id=user.id, entity='document_review',
                 entity_id=document.id, before={'extraction': previous}, after={'extraction': document.extraction}))
    db.commit()
    return document_view(document, True)
