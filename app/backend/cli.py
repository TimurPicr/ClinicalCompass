"""Controlled creation of doctor accounts. No public doctor-registration endpoint."""
import argparse
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select

from app.backend.core.security import passwords
from app.backend.models.user import User
from app.backend.schemas.clinical import Register
from app.database.connection import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="Создание врача администратором стенда")
    parser.add_argument("create-doctor", choices=["create-doctor"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass("Пароль врача (минимум 12 символов): ")
    if password != getpass("Повторите пароль: "):
        parser.error("Пароли не совпадают")
    try:
        data = Register(email=args.email, full_name=args.name, password=password)
    except ValidationError:
        parser.error("Проверьте email, имя и длину пароля (12–128 символов)")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == str(data.email).lower())):
            parser.error("Email уже существует")
        db.add(User(email=str(data.email).lower(), full_name=data.full_name,
                    password_hash=passwords.hash(data.password), role="doctor"))
        db.commit()
    print("Врач создан. Пригласите пациента из кабинета врача.")


if __name__ == "__main__":
    main()
