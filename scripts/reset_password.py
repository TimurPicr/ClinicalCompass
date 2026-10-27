"""Recovery links are issued manually after verifying the user's identity."""
import argparse
import secrets
from datetime import timedelta
from sqlalchemy import select
from database.connection import SessionLocal
from database.models import ResetToken, User, utcnow
from app.backend.auth import digest
from app.backend.config import settings

def main():
    parser = argparse.ArgumentParser(description='Выдать одноразовую ссылку восстановления (1 час)')
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if not user:
            parser.error('Пользователь не найден')
        token = secrets.token_urlsafe(32)
        db.add(ResetToken(user_id=user.id,token_hash=digest(token),expires_at=utcnow()+timedelta(hours=1)))
        db.commit()
        print(f'{settings.public_url}/?reset={token}')

if __name__ == '__main__':
    main()
