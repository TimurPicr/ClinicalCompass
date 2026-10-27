"""Reproducible local timings for the presentation; never a clinical validation.

AI cases use actual Ollama and isolated in-memory SQLite. PostgreSQL writes use
an uncommitted transient fixture that is rolled back. API reads use a demo login.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import platform
import statistics
import subprocess
from time import perf_counter
import uuid

import httpx
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.backend.ai import service
from app.backend.ai.ollama import OllamaClient
from app.backend.ai.queue import heavy_lock
from app.backend.config import settings
from app.backend.monitoring import record_event
from database.connection import SessionLocal, engine as postgres_engine
from database.models import AIJob, Base, Diary, Patient, User, utcnow
from scripts.evaluate_ai import build_case, checks_for


def distribution(values):
    return {'count': len(values), 'median_seconds': statistics.median(values) if values else None,
            'min_seconds': min(values) if values else None, 'max_seconds': max(values) if values else None}


def environment():
    def command(*args):
        try:
            return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    memory = command('sysctl', '-n', 'hw.memsize')
    result = {'cpu': command('sysctl', '-n', 'machdep.cpu.brand_string'),
            'ram_bytes': int(memory) if memory else None,
            'physical_cpu_count': command('sysctl', '-n', 'hw.physicalcpu'),
            'logical_cpu_count': command('sysctl', '-n', 'hw.logicalcpu'),
            'platform': platform.platform(), 'python': platform.python_version(),
            'llm_model': settings.llm_model, 'embedding_model': settings.embedding_model,
            'generation_options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 3000,
                                   'keep_alive': 0, 'think': False},
            'model_loading': 'Production keep_alive=0; each embedding and generation request unloads its model.'}
    try:
        with httpx.Client(base_url=settings.ollama_url, timeout=10, trust_env=False) as client:
            version = client.get('/api/version')
            version.raise_for_status()
            models = client.get('/api/tags')
            models.raise_for_status()
            result['ollama_version'] = version.json()['version']
            result['model_artifacts'] = [{key: item.get(key) for key in ('name', 'digest', 'size', 'details')}
                                         for item in models.json()['models']
                                         if item.get('name') in {settings.llm_model, settings.embedding_model}]
    except Exception as exc:
        result['model_metadata_error_type'] = type(exc).__name__
    return result


class TimedClient:
    def __init__(self, inner):
        self.inner = inner
        self.seconds = {'embed': 0.0, 'structured': 0.0}
        self.calls = {'embed': 0, 'structured': 0}
        self.last_result = None
        self.raw_model_content = None
        self.ollama_metadata = []
        inner.http.event_hooks['response'].append(self.capture_response)

    def capture_response(self, response):
        response.read()
        if not response.is_success:
            return
        data = response.json()
        metrics = {'path': response.request.url.path}
        for key in ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration'):
            if key in data:
                metrics[key + '_seconds'] = data[key] / 1_000_000_000
        for key in ('model', 'eval_count', 'prompt_eval_count', 'done_reason'):
            if key in data:
                metrics[key] = data[key]
        self.ollama_metadata.append(metrics)
        if response.request.url.path == '/api/chat':
            self.raw_model_content = data.get('message', {}).get('content')

    def embed(self, texts):
        started = perf_counter()
        self.calls['embed'] += 1
        try:
            return self.inner.embed(texts)
        finally:
            self.seconds['embed'] += perf_counter() - started

    def structured(self, schema, system, data):
        started = perf_counter()
        self.calls['structured'] += 1
        try:
            self.last_result = self.inner.structured(schema, system, data)
            return self.last_result
        finally:
            self.seconds['structured'] += perf_counter() - started


@contextmanager
def timed_snapshot(measured):
    original = service.clinical_snapshot

    def run(*args, **kwargs):
        started = perf_counter()
        try:
            value = original(*args, **kwargs)
            measured['input'] = value[1]
            return value
        finally:
            measured['snapshot_seconds'] = perf_counter() - started
    service.clinical_snapshot = run
    try:
        yield
    finally:
        service.clinical_snapshot = original


def benchmark_ai_case(name):
    memory_engine = create_engine('sqlite://')
    sample = {'case': name, 'manual_review': 'required', 'rag_sources': [],
              'persistence': 'isolated_sqlite_memory', 'queue_wait_included': False,
              'timing_scope': 'analyze_patient + SQLite commit/rollback + local regression rubric; excludes fixture preparation, queue wait and clinical HTTP routes'}
    try:
        Base.metadata.create_all(memory_engine)
        with Session(memory_engine, expire_on_commit=False) as db:
            patient = build_case(db, name, utcnow())
            model = OllamaClient()
            client = TimedClient(model)
            started = perf_counter()
            try:
                with timed_snapshot(sample):
                    analysis = service.analyze_patient(db, patient.id, client)
                    db.commit()
                sample.update(status='accepted', result=analysis.result,
                              status_after=patient.status)
                sample['quality_checks'] = checks_for(name, analysis.result, sample['input'], patient.status)
                sample['quality_checks_pass'] = all(check['passed'] for check in sample['quality_checks'])
            except Exception as exc:
                db.rollback()
                sample.update(status='rejected' if client.calls['structured'] else 'failed',
                              error_type=type(exc).__name__, quality_checks_pass=False)
                if client.last_result is not None:
                    sample['rejected_result'] = client.last_result.model_dump()
                elif client.raw_model_content is not None:
                    sample['rejected_raw_model_content'] = client.raw_model_content
            finally:
                sample.update(total_wall_seconds=perf_counter() - started,
                              embedding_seconds=client.seconds['embed'],
                              structured_seconds=client.seconds['structured'],
                              model_calls=client.calls, ollama_metadata=client.ollama_metadata)
                model.close()
    finally:
        memory_engine.dispose()
    return sample


def benchmark_postgres_diary(rounds):
    samples = []
    identity = uuid.uuid4().hex
    email = f'patient-{identity}@presentation-benchmark.invalid'
    result = {'operation': 'diary_insert_flush_rules_enqueue', 'database': 'PostgreSQL',
              'durable_commit_included': False, 'http_auth_serialization_included': False,
              'fixture_preparation_included': False,
              'method': 'Direct ORM path: Diary add+flush, production record_event (rules+AI queue), flush; all in one outer transaction, rolled back.',
              'samples': samples}
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection, expire_on_commit=False) as db:
                doctor = User(email=f'doctor-{identity}@presentation-benchmark.invalid',
                              name='Синтетический benchmark врач', role='doctor', password_hash='benchmark-no-login')
                patient = User(email=email, name='Синтетический benchmark пациент', role='patient', password_hash='benchmark-no-login')
                db.add_all([doctor, patient])
                db.flush()
                db.add(Patient(id=patient.id, doctor_id=doctor.id, record={}, diary_times=['20:00']))
                db.flush()
                result['postgres_version'] = db.scalar(text('SHOW server_version'))
                for index in range(rounds):
                    started = perf_counter()
                    sample = {'round': index + 1}
                    try:
                        entry = Diary(patient_id=patient.id, mood=7, anxiety=3, sleep=7, energy=7,
                                      wellbeing=7, comment='Синтетическая запись для измерения времени.')
                        db.add(entry)
                        db.flush()
                        record_event(db, patient.id, f'diary:{entry.id}')
                        db.flush()
                        sample['status'] = 'ok'
                    except Exception as exc:
                        sample.update(status='failed', error_type=type(exc).__name__)
                    sample['total_wall_seconds'] = perf_counter() - started
                    samples.append(sample)
                    if sample['status'] != 'ok':
                        break
                result['rows_before_rollback'] = {
                    'diary': db.scalar(select(func.count()).select_from(Diary).where(Diary.patient_id == patient.id)),
                    'queued_ai_jobs': db.scalar(select(func.count()).select_from(AIJob).where(AIJob.patient_id == patient.id)),
                }
        finally:
            if transaction.is_active:
                transaction.rollback()
    with SessionLocal() as db:
        result['fixture_users_remaining_after_rollback'] = db.scalar(select(func.count()).select_from(User).where(User.email == email))
    result['timings'] = distribution([s['total_wall_seconds'] for s in samples])
    result['success_count'] = sum(s['status'] == 'ok' for s in samples)
    return result


def benchmark_api_reads(base_url, rounds):
    result = {'base_url': base_url, 'method': 'Actual HTTP GET; persistent httpx client, cookie auth; login excluded; sequential reads per endpoint; no discarded warmup.',
              'auth_login_timed': False, 'operations': []}
    with httpx.Client(base_url=base_url, timeout=20, trust_env=False) as client:
        try:
            client.get('/api/auth/csrf').raise_for_status()
            client.headers['X-CSRF-Token'] = client.cookies.get('cc_csrf')
            response = client.post('/api/auth/login', json={'email': 'doctor.realistic-v2@example.com', 'password': 'DemoDoctor123!'})
            response.raise_for_status()
            client.headers['X-CSRF-Token'] = client.cookies.get('cc_csrf')
            patients = client.get('/api/patients')
            patients.raise_for_status()
            patient_id = patients.json()[0]['id']
            result['patient_id'] = patient_id
            for suffix in ('record', 'diary', 'chat'):
                operation = {'operation': f'GET /api/patients/:id/{suffix}', 'samples': []}
                for index in range(rounds):
                    started = perf_counter()
                    response = client.get(f'/api/patients/{patient_id}/{suffix}')
                    operation['samples'].append({'round': index + 1, 'total_wall_seconds': perf_counter() - started,
                                                  'status_code': response.status_code, 'response_bytes': len(response.content)})
                operation['timings'] = distribution([sample['total_wall_seconds'] for sample in operation['samples']])
                operation['success_count'] = sum(sample['status_code'] == 200 for sample in operation['samples'])
                result['operations'].append(operation)
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        finally:
            # End only the benchmark's new browser-independent login session.
            if client.cookies.get('cc_session'):
                client.post('/api/auth/logout')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('var/presentation/benchmark.json'))
    parser.add_argument('--case', action='append', choices=['improvement', 'deterioration', 'andrey_aviandrov'])
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--api-base-url', default='http://127.0.0.1:8010')
    args = parser.parse_args()
    report = {'created_at': utcnow().isoformat(), 'environment': environment(),
              'limitations': ['Synthetic cases only; not a clinical validation or load test.',
                              'Standalone AI: no queue wait, no OCR, no network RAG sources; retrieval corpus empty.',
                              'LLM latency includes model loading because production keep_alive=0.',
                              'Rejected AI attempts count in timing statistics; accepted JSON is not clinical correctness.',
                              'PostgreSQL diary timings exclude durable commit, HTTP, authentication and rendering.',
                              'Read HTTP timings use local demo database and persistent connection; no explicit cold-cache control or discarded warmup; not internet latency.',
                              'Other desktop/process load is not controlled; n=3 AI attempts is a small illustrative sample.',
                              'Snapshot timing uses isolated in-memory SQLite, not production PostgreSQL.'],
              'ai_samples': []}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
        args.output.chmod(0o600)

    save()
    with SessionLocal() as lock_db:
        with heavy_lock(lock_db) as acquired:
            if not acquired:
                report['error'] = 'AI-worker currently holds global model lock; no model benchmark run.'
                save()
                raise SystemExit(2)
            for name in args.case or ('improvement', 'deterioration', 'andrey_aviandrov'):
                print(f'AI {name}: actual Ollama call starting', flush=True)
                sample = benchmark_ai_case(name)
                report['ai_samples'].append(sample)
                report['ai_summary'] = {
                    'all_attempts': distribution([row['total_wall_seconds'] for row in report['ai_samples']]),
                    'embedding': distribution([row['embedding_seconds'] for row in report['ai_samples']]),
                    'structured': distribution([row['structured_seconds'] for row in report['ai_samples']]),
                    'snapshot': distribution([row.get('snapshot_seconds', 0) for row in report['ai_samples']]),
                    'accepted_count': sum(row['status'] == 'accepted' for row in report['ai_samples']),
                    'quality_checks_pass_count': sum(row['quality_checks_pass'] for row in report['ai_samples']),
                    'manual_review': 'required',
                }
                save()
                print(f'AI {name}: {sample["status"]}, total={sample["total_wall_seconds"]:.3f}s, structured={sample["structured_seconds"]:.3f}s', flush=True)
    print('PostgreSQL transient diary fixture: starting', flush=True)
    report['postgres_diary'] = benchmark_postgres_diary(args.rounds)
    save()
    print('Local HTTP API reads: starting', flush=True)
    report['api_reads'] = benchmark_api_reads(args.api_base_url, args.rounds)
    save()
    print(f'Report saved to {args.output}', flush=True)


if __name__ == '__main__':
    main()
