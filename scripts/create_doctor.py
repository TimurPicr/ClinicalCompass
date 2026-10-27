"""python -m scripts.create_doctor --email doctor@example.test --name 'Врач'"""
import argparse
from getpass import getpass
from pydantic import EmailStr, TypeAdapter, ValidationError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select
from app.backend.auth import hash_password
from database.connection import SessionLocal
from database.models import User

def main():
    parser = argparse.ArgumentParser(description='Создание врача')
    parser.add_argument('--email', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--timezone', default='Europe/Moscow')
    args = parser.parse_args()
    try:
        args.email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
        ZoneInfo(args.timezone)
    except (ValidationError, ZoneInfoNotFoundError, ValueError):
        parser.error('Проверьте email и часовой пояс')
    args.name = args.name.strip()
    if not 2 <= len(args.name) <= 160:
        parser.error('Имя должно содержать 2–160 символов')
    password = getpass('Пароль (не менее 12 символов): ')
    if not 12 <= len(password) <= 256:
        parser.error('Пароль должен содержать 12–256 символов')
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == args.email.lower())):
            parser.error('Email уже зарегистрирован')
        db.add(User(email=args.email.lower(),name=args.name,role='doctor',timezone=args.timezone,password_hash=hash_password(password)))
        db.commit()
    print('Врач создан')

if __name__ == '__main__':
    main()
