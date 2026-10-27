"""Every test gets a migrated, isolated database. Never use application .env DB."""
import os
import uuid
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "synthetic-test-signing-key-at-least-32-characters"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.backend.core.config import settings
from app.backend.core.security import passwords
from app.backend.main import app
from app.backend.models.user import User
from app.database.connection import get_db

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-password-12345"


@pytest.fixture
def db_factory(tmp_path, monkeypatch):
    pg_url = os.getenv("TEST_DATABASE_URL")
    admin = None
    schema = None
    if pg_url:
        parsed = make_url(pg_url)
        if not parsed.database or not parsed.database.endswith("_test"):
            pytest.fail("TEST_DATABASE_URL must name a dedicated database ending in _test")
        schema = "test_" + uuid.uuid4().hex
        admin = create_engine(pg_url)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = parsed.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    else:
        url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = create_engine(url, connect_args={"check_same_thread": False} if not pg_url else {})
    if not pg_url:
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    factory = sessionmaker(engine, expire_on_commit=False)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        yield factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture
def client(db_factory):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def actors(db_factory):
    with db_factory() as db:
        records = [User(email=f"{name}@example.com", full_name=name, role=role,
                        password_hash=passwords.hash(PASSWORD))
                   for name, role in [("doctor", "doctor"), ("otherdoctor", "doctor"),
                                      ("patient", "patient"), ("otherpatient", "patient")]]
        db.add_all(records)
        db.commit()
        records[2].doctor_id = records[0].id
        records[3].doctor_id = records[1].id
        db.commit()
        return {row.full_name: row for row in records}


def signed_in(actor):
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": actor.email, "password": PASSWORD}).status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("cc_csrf")
    return client


@pytest.fixture
def patient_client(actors):
    with signed_in(actors["patient"]) as client:
        yield client


@pytest.fixture
def doctor_client(actors):
    with signed_in(actors["doctor"]) as client:
        yield client


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    messages = []
    def capture(email, token):
        messages.append({"email": email, "token": token})
    monkeypatch.setattr('app.backend.api.patients.send_invitation', capture)
    return messages
