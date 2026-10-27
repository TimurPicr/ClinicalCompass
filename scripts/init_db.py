import subprocess
import sys
from app.backend.clinical import ensure_standard_templates
from database.connection import SessionLocal

def main():
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True)
    with SessionLocal() as db:
        ensure_standard_templates(db)
        db.commit()
    print('Миграции применены, стандартные шкалы добавлены')

if __name__=='__main__':
    main()
