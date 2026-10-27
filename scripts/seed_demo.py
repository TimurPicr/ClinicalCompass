"""Idempotent fictional histories. No prewritten text is presented as generated AI analysis."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import textwrap
import uuid
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.backend.auth import hash_password
from app.backend.clinical import ensure_standard_templates, evaluate_rules
from app.backend.clinical_common import aware
from app.backend.config import settings
from app.backend.knowledge.service import import_text
from database.connection import SessionLocal
from database.models import (Assignment, Audit, Diary, Document, Intake, Message, Patient,
                             Prescription, PrescriptionVersion, QuestionnaireTemplate,
                             Response, User, utcnow)
from scripts.demo_cases import CASES

DOCTOR_PASSWORD = 'DemoDoctor123!'
PATIENT_PASSWORD = 'DemoPatient123!'
DEMO_VERSION = 'realistic-v2'
ZONE = ZoneInfo('Europe/Moscow')


def demo_email(key, cohort=None):
    if cohort is not None and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', cohort):
        raise ValueError('Cohort: от 1 до 32 латинских строчных букв, цифр или дефисов')
    return f'{key}.{cohort}@example.com' if cohort else f'{key}@example.com'


def _local_at(day, clock):
    hour, minute = map(int, clock.split(':'))
    return datetime.combine(day, datetime.min.time(), ZONE).replace(hour=hour, minute=minute).astimezone(timezone.utc)


def _record(case, anchor):
    prescription = case['prescription']
    offsets = prescription['versions'] if prescription else [(-20, '')]
    dates = {
        'initial_date': (anchor - timedelta(days=20)).date().isoformat(),
        'treatment_date': (anchor + timedelta(days=offsets[0][0])).date().isoformat(),
        'change_date': (anchor + timedelta(days=offsets[-1][0])).date().isoformat(),
        'latest_date': anchor.date().isoformat(),
    }
    return {
        'diagnosis_code': case['diagnosis_code'], 'diagnosis': case['diagnosis'],
        **{key: value.format(**dates) for key, value in case['record'].items()},
        'notes': f'СИНТЕТИЧЕСКИЙ пациент. Демосценарий {DEMO_VERSION}/{case["key"]}. '
                 'Имя, история, обследования и врачебные назначения вымышлены; это проверка программы, не клиническая валидация.',
    }


def _seed_treatment(db, patient_id, doctor_id, case, anchor):
    spec = case['prescription']
    if not spec:
        return
    first = _local_at((anchor + timedelta(days=spec['versions'][0][0])).date(), '00:00')
    prescription = Prescription(patient_id=patient_id, doctor_id=doctor_id,
                                created_at=first, current_version=len(spec['versions']))
    db.add(prescription)
    db.flush()
    versions = []
    for number, (offset, dose) in enumerate(spec['versions'], 1):
        changed = _local_at((anchor + timedelta(days=offset)).date(), '00:00')
        data = {'name': spec['name'], 'substance': spec['substance'], 'dose': dose,
                'unit': 'мг', 'times': ['09:00'], 'start_date': first.astimezone(ZONE).date().isoformat(),
                'end_date': None, 'comment': 'Вымышленное назначение врача в синтетической истории; не рекомендация лечения.'}
        row = PrescriptionVersion(prescription_id=prescription.id, version=number,
                                  created_at=changed, data=data)
        db.add(row)
        versions.append(row)
    for index in range(21):
        scheduled = _local_at((anchor - timedelta(days=20 - index)).date(), '09:00')
        version = max((v for v in versions if aware(v.created_at) <= scheduled), key=lambda v: v.version)
        skipped = case['key'] == 'pavel' and index in {16, 18}
        side_effect = case['key'] == 'pavel' and index == 17
        db.add(Intake(patient_id=patient_id, prescription_id=prescription.id, version=version.version,
                      scheduled_at=scheduled, actual_at=None if skipped else scheduled + timedelta(minutes=(index % 4) * 3 + 2),
                      status='skipped' if skipped else 'taken',
                      reason=('Забыл таблетку в дороге' if index == 16 else 'Опасался повторения тошноты') if skipped else '',
                      side_effect='Тошнота примерно через час после приёма, продолжалась около получаса' if side_effect else '',
                      severity=4 if side_effect else 0))


def _seed_observations(db, patient_id, case, anchor, templates):
    for index in range(21):
        phase = index // 7
        metrics = list(case['trajectory'][phase])
        # Reproducible daily variation; the phase trajectory remains visible.
        metric = index % 5
        metrics[metric] = max(0, min(10, metrics[metric] + (1 if index % 3 == 0 else -1 if index % 3 == 1 else 0)))
        db.add(Diary(patient_id=patient_id, created_at=anchor - timedelta(days=20 - index),
                     **dict(zip(('mood', 'anxiety', 'sleep', 'energy', 'wellbeing'), metrics)),
                     comment=case['comments'][phase][index % 7]))
    for kind in ('phq9', 'gad7'):
        template = templates[kind]
        snapshot = {'name': template.name, 'kind': kind, 'version': template.version, 'schema': template.schema}
        for offset, values in zip((20, 10, 0), case[kind]):
            completed = anchor - timedelta(days=offset)
            assignment = Assignment(patient_id=patient_id, template_id=template.id, snapshot=snapshot,
                                    schedule={'frequency': 'once'}, due_at=completed, active=False,
                                    created_at=completed - timedelta(hours=1))
            db.add(assignment)
            db.flush()
            answers = {f'q{i}': value for i, value in enumerate(values, 1)}
            db.add(Response(patient_id=patient_id, assignment_id=assignment.id, answers=answers,
                            score=sum(values), created_at=completed,
                            idempotency_key=f'{DEMO_VERSION}:{kind}:{offset}'))
        db.add(Assignment(patient_id=patient_id, template_id=template.id, snapshot=snapshot,
                          schedule={'frequency': 'weekly', 'times': ['20:00']},
                          due_at=anchor + timedelta(days=7), created_at=anchor))


def _document_font():
    for path in ('/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(path, 25)
        except OSError:
            continue
    return ImageFont.load_default(size=25)


def _seed_document(db, patient_id, case, record, anchor):
    """OCR original repeats the case's findings; extraction still needs review."""
    paragraphs = ['СИНТЕТИЧЕСКИЙ ДОКУМЕНТ — НЕ РЕАЛЬНЫЙ ПАЦИЕНТ',
                  f'Пациент: {case["name"]}', f'Контрольная запись: {anchor.date().isoformat()}',
                  f'Диагноз: {record["diagnosis_code"]} — {record["diagnosis"]}',
                  f'Анамнез: {record["anamnesis"]}', f'Аллергии: {record["allergies"]}',
                  f'Обследования: {record["examinations"]}',
                  'Все сведения вымышлены. Документ предназначен только для проверки OCR и просмотра врачом.']
    lines = [line for paragraph in paragraphs for line in textwrap.wrap(paragraph, width=88)]
    image = Image.new('RGB', (1500, 100 + len(lines) * 38), 'white')
    draw = ImageDraw.Draw(image)
    font = _document_font()
    for index, line in enumerate(lines):
        draw.text((35, 35 + index * 38), line, fill='black', font=font)
    directory = Path(settings.upload_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_name = uuid.uuid4().hex + '.png'
    path = directory / storage_name
    image.save(path)
    path.chmod(0o600)
    document = Document(patient_id=patient_id, uploader_id=patient_id,
                        name=f'Синтетическая выписка — {case["name"]}.png', storage_name=storage_name,
                        mime='image/png', size=path.stat().st_size,
                        checksum=hashlib.sha256(path.read_bytes()).hexdigest(), created_at=anchor)
    db.add(document)
    db.flush()
    from app.backend.ai.queue import enqueue
    enqueue(db, patient_id, 'document', {'document_id': document.id}, f'demo-document:{document.id}')


def seed(db, *, now=None, cohort=None):
    """Existing accounts are untouched. A named cohort also has a separate doctor."""
    doctor_email = demo_email('doctor', cohort)
    now = aware(now or utcnow()).astimezone(timezone.utc)
    # End yesterday at 20:00 local: even an early-morning run has no future events.
    anchor = _local_at(now.astimezone(ZONE).date() - timedelta(days=1), '20:00')
    ensure_standard_templates(db)
    doctor = db.scalar(select(User).where(User.email == doctor_email))
    if doctor and doctor.role != 'doctor':
        raise ValueError('Email демонстрационного врача занят аккаунтом другой роли; выберите --cohort')
    if not doctor:
        doctor = User(email=doctor_email, name='Елена Сергеевна Волкова', role='doctor',
                      password_hash=hash_password(DOCTOR_PASSWORD), timezone='Europe/Moscow')
        db.add(doctor)
        db.flush()
    templates = {kind: db.scalar(select(QuestionnaireTemplate).where(QuestionnaireTemplate.kind == kind))
                 for kind in ('phq9', 'gad7')}
    for case in CASES:
        email = demo_email(case['key'], cohort)
        if db.scalar(select(User.id).where(User.email == email)):
            continue
        user = User(email=email, name=case['name'], role='patient',
                    password_hash=hash_password(PATIENT_PASSWORD), timezone='Europe/Moscow',
                    created_at=anchor - timedelta(days=20))
        db.add(user)
        db.flush()
        record = _record(case, anchor)
        patient = Patient(id=user.id, doctor_id=doctor.id, birth_date=case['birth_date'],
                          monitoring_started_at=anchor - timedelta(days=20), diary_times=['20:00'],
                          last_activity=anchor, record=record, reported_record=case['reported'])
        db.add(patient)
        db.flush()
        # This is a retrospective case summary as of the last observation, not
        # a claim that its later findings were already known at enrollment.
        db.add(Audit(patient_id=user.id, actor_id=doctor.id, entity='record', entity_id=user.id,
                     before={}, after=record, created_at=anchor))
        _seed_treatment(db, user.id, doctor.id, case, anchor)
        _seed_observations(db, user.id, case, anchor, templates)
        db.add(Message(patient_id=user.id, sender_id=doctor.id, text=case['doctor_message'],
                       created_at=anchor - timedelta(hours=2)))
        db.add(Message(patient_id=user.id, sender_id=user.id, text=case['patient_message'], created_at=anchor))
        _seed_document(db, user.id, case, record, anchor)
        db.flush()
        evaluate_rules(db, user.id, now=now)
        from app.backend.ai.queue import enqueue
        enqueue(db, user.id, 'analysis', {'trigger': 'demo-seed', 'version': DEMO_VERSION},
                f'demo-analysis:{DEMO_VERSION}:{user.id}')
    import_text(db, source='demo', external_id='synthetic-monitoring-v1',
                title='СИНТЕТИЧЕСКИЙ материал для проверки RAG',
                url='https://example.org/synthetic-monitoring', category='clinical_guideline',
                text='СИНТЕТИЧЕСКИЙ ДОКУМЕНТ. Не является медицинским источником или клинической рекомендацией. '
                     'Демонстрационный мониторинг включает дневник, ответы на опросники, регистрацию приёма препаратов '
                     'и обсуждение изменений с врачом. Временное совпадение жалобы и изменения назначения не доказывает причинную связь. '
                     'Сведения автоматически не подтверждаются. Все выводы в этом учебном сценарии проверяет врач. ' * 5)
    db.commit()
    return doctor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', help='Отдельные demo-аккаунты, например realistic-v2; существующие данные сохраняются')
    args = parser.parse_args()
    try:
        demo_email('doctor', args.cohort)
    except ValueError as exc:
        parser.error(str(exc))
    with SessionLocal() as db:
        doctor = seed(db, cohort=args.cohort)
        doctor_email = doctor.email
        own_emails = []
        for case in CASES:
            user = db.scalar(select(User).where(User.email == demo_email(case['key'], args.cohort)))
            if user and db.get(Patient, user.id) and db.get(Patient, user.id).doctor_id == doctor.id:
                own_emails.append(user.email)
    print('Синтетические данные созданы; существующие аккаунты и их история не изменены.')
    print(f'Врач: {doctor_email} / {DOCTOR_PASSWORD}')
    print('Пациенты: ' + ', '.join(own_emails) + ' / ' + PATIENT_PASSWORD)
    print('Пароли действуют только для вновь созданных аккаунтов. Для изолированной новой демонстрации: --cohort realistic-v2.')
    print('AI-сводки появятся после выполнения локальным обработчиком; готовые AI-ответы не подставляются.')


if __name__ == '__main__':
    main()
