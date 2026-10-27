import hashlib
import json
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.backend.ai.ollama import UNTRUSTED_INSTRUCTIONS
from app.backend.ai.schemas import (CRITICAL_ASSESSMENT_NOTICE, analysis_schema,
                                    validate_analysis_evidence, validate_citations)
from app.backend.clinical_common import aware
from app.backend.config import settings
from app.backend.knowledge.service import retrieve
from database.models import (AIAnalysis, Alert, Assignment, Diary, Intake, Patient,
                             Prescription, PrescriptionVersion, Response, User, utcnow)


def clipped(value):
    if isinstance(value, str):
        return value[:700]
    if isinstance(value, dict):
        return {key: clipped(item) for key, item in list(value.items())[:25]}
    if isinstance(value, list):
        return [clipped(item) for item in value[:15]]
    return value


def clinical_snapshot(db, patient_id):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise ValueError('Пациент не найден')
    now = utcnow()
    diary = db.scalars(select(Diary).where(Diary.patient_id == patient_id, Diary.created_at <= now)
                      .order_by(Diary.created_at.desc(), Diary.id.desc()).limit(10)).all()
    answers = db.scalars(select(Response).join(Assignment, Response.assignment_id == Assignment.id)
                        .where(Response.patient_id == patient_id, Assignment.patient_id == patient_id, Response.created_at <= now)
                        .order_by(Response.created_at.desc(), Response.id.desc()).limit(10)).all()
    intakes = db.scalars(select(Intake).join(Prescription, Intake.prescription_id == Prescription.id)
                        .where(Intake.patient_id == patient_id, Prescription.patient_id == patient_id, Intake.scheduled_at <= now)
                        .order_by(Intake.scheduled_at.desc(), Intake.id.desc()).limit(15)).all()
    prescriptions = db.scalars(select(Prescription).where(Prescription.patient_id == patient_id, Prescription.created_at <= now)
                              .order_by(Prescription.created_at.desc(), Prescription.id.desc())).all()
    versions = []
    intake_versions = {(row.prescription_id, row.version) for row in intakes}
    for index, prescription in enumerate(prescriptions):
        if index >= 10 and not any(pid == prescription.id for pid, _ in intake_versions):
            continue
        rows = db.scalars(select(PrescriptionVersion).where(PrescriptionVersion.prescription_id == prescription.id,
                                                           PrescriptionVersion.created_at <= now)
                          .order_by(PrescriptionVersion.version.desc())).all()
        versions.extend({'prescription_id': prescription.id, 'version': row.version,
                         'prescription_active': prescription.active,
                         'current_version': rows[0].version,
                         'created_at': aware(row.created_at).isoformat(), 'data': clipped(row.data)}
                        for i, row in enumerate(rows) if i < 4 or (prescription.id, row.version) in intake_versions)
    def fields(row, names):
        return {name: aware(getattr(row, name)).isoformat() if name.endswith('_at') and getattr(row, name) is not None
                else clipped(getattr(row, name)) for name in names}
    definitions = {}
    for answer in answers:
        if str(answer.assignment_id) in definitions:
            continue
        assignment = db.get(Assignment, answer.assignment_id)
        if assignment:
            form = assignment.snapshot
            kind = form.get('kind')
            definitions[str(assignment.id)] = {
                'name': form.get('name'), 'kind': kind, 'version': form.get('version'),
                'score_max': {'phq9': 27, 'gad7': 21}.get(kind),
                'instructions': clipped(form.get('schema', {}).get('instructions', '')),
                'questions': [{key: clipped(question.get(key)) for key in ('id', 'label', 'type')}
                              for question in form.get('schema', {}).get('questions', [])],
            }
    alerts = db.scalars(select(Alert).where(Alert.patient_id == patient_id, Alert.source.startswith('rule:'),
                                           Alert.state.notin_(['dismissed', 'resolved']))
                       .order_by((Alert.level == 'red').desc(), Alert.created_at.desc(), Alert.id.desc())).all()
    if sum(a.level == 'red' for a in alerts) > 20:
        raise ValueError('Слишком много критических сигналов для безопасного контекста AI')
    user = db.get(User, patient_id)
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    snapshot = {
        'as_of': now.isoformat(), 'event_order': 'newest_first', 'timezone': user.timezone,
        'birth_date': patient.birth_date.isoformat() if patient.birth_date else None,
        'age': ((today.year - patient.birth_date.year
                 - ((today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)))
                if patient.birth_date else None),
        'confirmed_record': clipped(patient.record), 'patient_reported_unconfirmed': clipped(patient.reported_record),
        'deterministic_status': patient.status,
        'active_alerts': [fields(row, ('id', 'level', 'category', 'source', 'reason', 'state')) for row in alerts[:20]],
        'alert_counts': {'red': sum(a.level == 'red' for a in alerts), 'yellow': sum(a.level == 'yellow' for a in alerts)},
        'diary_scale_direction': 'mood/sleep/energy/wellbeing: 0 худшее,10 лучшее; anxiety: 0 нет,10 максимальная; sleep — качество сна, НЕ часы',
        'diary': [fields(row, ('id', 'created_at', 'mood', 'anxiety', 'sleep', 'energy', 'wellbeing', 'comment')) for row in diary],
        'questionnaires': [fields(row, ('id', 'created_at', 'assignment_id', 'score', 'answers')) for row in answers],
        'questionnaire_definitions': definitions,
        'intakes': [fields(row, ('id', 'scheduled_at', 'actual_at', 'prescription_id', 'version', 'status', 'side_effect', 'severity', 'reason')) for row in intakes],
        'treatment_versions': versions,
        'context_limits': 'Окно до 10 дневников, 10 ответов, 15 приёмов, 20 активных сигналов правил; старые события могут отсутствовать. Отсутствие отметки не означает пропуск.',
    }
    def update_refs():
        used = {str(row['assignment_id']) for row in snapshot['questionnaires']}
        snapshot['questionnaire_definitions'] = {key: value for key, value in definitions.items() if key in used}
        snapshot['evidence_refs'] = (
            [f'{prefix}:{row["id"]}' for key, prefix in [('diary', 'diary'), ('questionnaires', 'questionnaire'),
                                                       ('intakes', 'intake'), ('active_alerts', 'alert')] for row in snapshot[key]]
            + [f'{key}:{field}' for key in ('confirmed_record', 'patient_reported_unconfirmed') for field in snapshot[key]]
            + [f'treatment:{row["prescription_id"]}:{row["version"]}' for row in snapshot['treatment_versions']])
    update_refs()
    # Never truncate critical alerts to fit ordinary observations. A bounded
    # context fails explicitly if even the essential evidence cannot fit.
    for key in ('intakes', 'questionnaires', 'diary', 'treatment_versions'):
        while len(json.dumps(snapshot, default=str, ensure_ascii=False)) > 13_000 and len(snapshot[key]) > 2:
            if key == 'treatment_versions':
                required = {(row['prescription_id'], row['version']) for row in snapshot['intakes']}
                removable = [i for i, row in enumerate(snapshot[key])
                             if row['version'] != row['current_version'] and (row['prescription_id'], row['version']) not in required]
                if not removable:
                    break
                snapshot[key].pop(removable[-1])
            else:
                snapshot[key].pop()
            update_refs()
    if len(json.dumps(snapshot, default=str, ensure_ascii=False)) > 13_000:
        raise ValueError('Клинический контекст не помещается без потери существенных данных')
    return patient, snapshot


def analyze_patient(db, patient_id, client):
    patient, snapshot = clinical_snapshot(db, patient_id)
    medicines = [item['data'].get('substance') or item['data'].get('active_ingredient') or item['data'].get('name', '') for item in snapshot['treatment_versions']]
    query = ' '.join([str(patient.record.get('diagnosis', '')), *medicines[:5], 'побочные эффекты динамика лечения'])[:1000]
    sources = retrieve(db, query, client, limit=5, max_chars=5500, clinical_only=True)
    prompt = UNTRUSTED_INSTRUCTIONS + (
        'Подготовь сводку наблюдения на основании только предоставленных данных. '
        'Отделяй факты, гипотезы и рекомендации для рассмотрения врачом. '
        'В facts указывай конкретные наблюдения, даты и значения шкал, если они доступны. '
        'Временное совпадение симптома и изменения препарата не доказывает причинность. '
        'patient_summary: понятное пациенту описание без рекомендаций по изменению лечения; '
        'changes: только наблюдаемые изменения, без лечебных советов. '
        'Не снижай deterministic_status и не отменяй критические правила. '
        'События идут от новых к старым; сравнивай даты, не порядок индексов. '
        'sleep — качество сна 0–10, не продолжительность в часах. '
        'Подтверждённую карту и patient_reported_unconfirmed не объединяй; противоречия обозначай как требующие проверки. '
        'Применяй к приёму его историческую версию; prescription_active=false или прошедший end_date не означает текущее лечение. '
        'Пропущенная отметка не доказывает пропуск приёма; считай только status=skipped. '
        'Опросники — скрининг, не новый диагноз. Не приписывай PHQ-9 вопрос 9 шкале GAD-7. '
        'Пункт 9 PHQ-9 касается мыслей о смерти или самоповреждении, НЕ уровня тревожности и НЕ доказанного факта попытки. '
        'Для каждого риска evidence — непустой список ТОЧНЫХ строк из evidence_refs, например diary:12 или alert:3, без своего текста. '
        'risks — только конкретные основания для дополнительной оценки: ухудшение, активный сигнал, новая жалоба или конфликт данных. '
        'Само наличие уже известного диагноза или записанной аллергии без нового события/взаимодействия не является новым alarm. '
        'При улучшении без активных сигналов и новых проблем возвращай risks=[]. '
        'Каждый красный active_alerts отрази красным риском с evidence alert:<id>, даже если более поздние шкалы стали ниже. '
        'Наличие показания или торгового названия не доказывает необходимость конкретного бренда. '
        'При предполагаемом экстренном риске укажи необходимость неотложной помощи, '
        'не обещай круглосуточного наблюдения. '
        'sources содержит только точные id,url,page из retrieved_sources; '
        'нет подходящего источника — пустой sources и явно обозначенная неопределённость. '
        'Не делай клинических выводов на основании одной библиографической карточки без полного текста. '
        'Источники source=demo являются синтетическими техническими примерами, '
        'а не медицинскими доказательствами; не обосновывай ими клинические выводы.'
    )
    if any(alert['level'] == 'red' for alert in snapshot['active_alerts']):
        prompt += (
            '\nВ этом контексте есть известный красный сигнал. '
            f'Именно поле patient_summary должно начинаться дословно: {CRITICAL_ASSESSMENT_NOTICE} '
            'Сообщения только в summary или explanation недостаточно. '
            'Пункт 9 PHQ-9 — скрининг мыслей о смерти/самоповреждении, не шкала тревоги и не факт попытки. '
            'Отрази каждый такой сигнал в risks с level=red и его alert:<id>.'
        )
    else:
        prompt += '\nНе выдумывай срочность или красный сигнал по одному наличию диагноза.'
    if (snapshot['confirmed_record'].get('allergies')
            and snapshot['patient_reported_unconfirmed'].get('allergies')):
        prompt += (
            '\nСопоставь confirmed_record.allergies и patient_reported_unconfirmed.allergies. '
            'Если пациент отрицает подтверждённую аллергию, явно укажи в facts оба источника '
            'и необходимость уточнения расхождения; отрицание пациента не отменяет подтверждённую аллергию. '
            'Различие формулировок само по себе не доказывает противоречие.'
        )
    result = validate_citations(client.structured(analysis_schema(snapshot), prompt,
                                  {'patient': snapshot, 'retrieved_sources': sources}), sources)
    validate_analysis_evidence(result, snapshot)
    analysis = AIAnalysis(patient_id=patient_id, result=result.model_dump(), model=settings.llm_model)
    db.add(analysis)
    db.flush()
    rule_levels = {f'alert:{a["id"]}': a['level'] for a in snapshot['active_alerts']}
    rule_origins = {}
    for item in snapshot['active_alerts']:
        alert = db.get(Alert, item['id'])
        kind, _, origin_id = alert.fingerprint.removeprefix(f'{patient_id}:').partition(':')
        origin = ('questionnaire' if kind in {'phq9-item9', 'phq9-score', 'gad7-score'}
                  else 'intake' if kind == 'side-effect' else None)
        refs = {f'alert:{alert.id}'}
        if origin:
            refs.add(f'{origin}:{origin_id}')
        rule_origins[f'alert:{alert.id}'] = refs
    levels = set()
    for risk in result.risks:
        # A summary of a known rule is not a new independent clinical finding.
        # Otherwise dismissing the original leaves a persistent AI shadow red.
        mirrored = [ref for ref in risk.evidence if ref in rule_levels
                    and (rule_levels[ref] == 'red' or risk.level == 'yellow')]
        covered_refs = set().union(*(rule_origins[ref] for ref in mirrored))
        if mirrored and set(risk.evidence) <= covered_refs:
            continue
        fingerprint = f'ai-evidence:{patient_id}:' + hashlib.sha256(
            json.dumps([risk.level, sorted(set(risk.evidence))], ensure_ascii=False).encode()).hexdigest()
        existing = db.scalar(select(Alert).where(Alert.fingerprint == fingerprint))
        if existing:
            if existing.state not in {'dismissed', 'resolved'}:
                levels.add(existing.level)
            continue
        db.add(Alert(patient_id=patient_id, level=risk.level, category='ai',
                     reason='Предположение AI, требуется оценка врача: ' + risk.description,
                     source=f'AIAnalysis:{analysis.id}', source_url=result.sources[0].url if result.sources else '',
                     fingerprint=fingerprint))
        levels.add(risk.level)
    elevated = 'red' if 'red' in levels else 'yellow' if 'yellow' in levels else None
    if elevated:
        # Compare in PostgreSQL at UPDATE time: a new critical rule may have
        # run while the model was thinking, after this ORM snapshot was read.
        permitted = ['green', 'yellow'] if elevated == 'red' else ['green']
        db.execute(update(Patient).where(Patient.id == patient_id, Patient.status.in_(permitted))
                   .values(status=elevated), execution_options={'synchronize_session': False})
        db.expire(patient, ['status'])
    return analysis


def analysis_view(analysis, role):
    if not analysis:
        return None
    result = analysis.result
    if role != 'doctor':
        # The patient endpoint deliberately does not serialize hypotheses,
        # recommendations or clinical explanations intended for the doctor.
        result = {key: result.get(key) for key in ('patient_summary', 'changes', 'sources')}
    return {'id': analysis.id, 'created_at': analysis.created_at, 'model': analysis.model, 'result': result}
