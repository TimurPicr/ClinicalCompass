import os
os.environ['DATABASE_URL']='sqlite://'
os.environ['PUBLIC_URL']='http://localhost:5174'
os.environ['ALLOWED_ORIGINS']='http://testserver,http://localhost:5174'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from database.models import Base, Patient, User
from database.connection import get_db
from app.backend.auth import hash_password
from app.backend.main import app

@pytest.fixture
def db():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as session:
        yield session
    engine.dispose()

@pytest.fixture
def doctor(db):
    row=User(email='doctor@example.com',name='Тестовый врач',role='doctor',password_hash=hash_password('TestPassword123!'))
    db.add(row);db.commit()
    return row

@pytest.fixture
def patient(db,doctor):
    row=User(email='patient@example.com',name='Тестовый пациент',role='patient',password_hash=hash_password('TestPassword123!'))
    db.add(row);db.flush();db.add(Patient(id=row.id,doctor_id=doctor.id));db.commit()
    return row

@pytest.fixture
def other_doctor(db):
    row=User(email='other@example.com',name='Другой врач',role='doctor',password_hash=hash_password('TestPassword123!'))
    db.add(row);db.commit()
    return row

@pytest.fixture
def client(db):
    app.dependency_overrides[get_db]=lambda:db
    with TestClient(app) as client:
        client.get('/api/auth/csrf')
        client.headers['X-CSRF-Token']=client.cookies.get('cc_csrf')
        yield client
    app.dependency_overrides.clear()

def sign_in(client,email):
    response=client.post('/api/auth/login',json={'email':email,'password':'TestPassword123!'})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=client.cookies.get('cc_csrf')
    return client

@pytest.fixture
def doctor_client(client,doctor):
    return sign_in(client,doctor.email)

@pytest.fixture
def patient_client(client,patient):
    return sign_in(client,patient.email)
