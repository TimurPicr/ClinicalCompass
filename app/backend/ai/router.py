import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.backend.ai.queue import enqueue, job_view, utcnow
from app.backend.ai.service import analysis_view
from app.backend.auth import accessible_patient, current_user, doctor_user
from database.connection import get_db
from database.models import AIAnalysis, AIJob

router = APIRouter(prefix='/api', tags=['ai'])


@router.get('/patients/{patient_id}/ai')
def patient_ai(patient_id: int, user=Depends(current_user), db=Depends(get_db)):
    accessible_patient(db, user, patient_id)
    analysis = db.scalar(select(AIAnalysis).where(AIAnalysis.patient_id == patient_id)
                         .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc()).limit(1))
    jobs = db.scalars(select(AIJob).where(AIJob.patient_id == patient_id)
                      .order_by(AIJob.created_at.desc(), AIJob.id.desc()).limit(12)).all()
    views = [job_view(job) for job in jobs]
    if user.role != 'doctor':
        # Error strings contain only a safe error category, never clinical input.
        for view in views:
            if view['error']:
                view['error'] = 'Анализ временно недоступен'
    return {'analysis': analysis_view(analysis, user.role), 'jobs': views}


@router.post('/patients/{patient_id}/ai', status_code=202)
def request_analysis(patient_id: int, user=Depends(doctor_user), db=Depends(get_db)):
    accessible_patient(db, user, patient_id)
    pending = db.scalar(select(AIJob).where(AIJob.patient_id == patient_id, AIJob.kind == 'analysis',
                                           AIJob.status.in_(['pending', 'running'])).limit(1))
    job = pending or enqueue(db, patient_id, payload={'trigger': 'doctor'}, dedupe_key=f'manual:{patient_id}:{uuid.uuid4().hex}')
    db.commit()
    return job_view(job)


@router.post('/ai/jobs/{job_id}/retry')
def retry_job(job_id: int, user=Depends(doctor_user), db=Depends(get_db)):
    job = db.get(AIJob, job_id)
    if not job:
        raise HTTPException(404, 'Задача не найдена')
    if job.patient_id:
        accessible_patient(db, user, job.patient_id)
    if job.status != 'failed':
        raise HTTPException(409, 'Повтор доступен для задач со статусом failed')
    job.status, job.attempts, job.available_at = 'pending', 0, utcnow()
    job.error, job.finished_at, job.locked_at = None, None, None
    db.commit()
    return job_view(job)
