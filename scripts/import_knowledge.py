"""Import a legally obtained reference; indexing runs in the AI worker."""
import argparse
from pathlib import Path
from urllib.parse import urlparse

from app.backend.documents import extract_pages
from app.backend.knowledge.service import CATEGORIES, import_text
from database.connection import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--source', choices=['grls', 'minzdrav', 'pubmed', 'local', 'demo'], required=True)
    parser.add_argument('--external-id', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--category', choices=sorted(CATEGORIES), required=True)
    parser.add_argument('--published-at')
    parser.add_argument('--version', default='', help='Версия источника, отдельно от внутреннего номера версии')
    parser.add_argument('--ingredients', default='', help='Действующие вещества через запятую')
    args = parser.parse_args()
    if urlparse(args.url).scheme not in {'http', 'https'}:
        parser.error('Нужна HTTP(S)-ссылка на официальный источник')
    if args.file.stat().st_size > 15 * 1024 * 1024:
        parser.error('Файл больше 15 МБ')
    if args.file.suffix.lower() == '.pdf':
        pages = extract_pages(args.file, 'application/pdf')
        text = '\n\n'.join(page['text'] for page in pages)
    elif args.file.suffix.lower() == '.txt':
        text, pages = args.file.read_text(encoding='utf-8-sig'), None
    else:
        parser.error('Разрешены PDF и UTF-8 TXT')
    with SessionLocal() as db:
        document, created = import_text(db, source=args.source, external_id=args.external_id,
                                        title=args.title, url=args.url, category=args.category,
                                        text=text, pages=pages, published_at=args.published_at,
                                        metadata={'publication_version': args.version,
                                                  'active_ingredients': [value.strip() for value in args.ingredients.split(',') if value.strip()]})
        db.commit()
        print(f'Документ {document.id}, версия {document.version}: ' +
              ('поставлен на индексацию' if created else 'не изменился; эмбеддинги сохранены'))


if __name__ == '__main__':
    main()
