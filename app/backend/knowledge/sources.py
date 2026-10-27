"""Small, rate-limited official adapters. No browser scraping or CAPTCHA bypass."""
import time
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import select

from app.backend.ai.queue import enqueue, utcnow
from app.backend.config import settings
from app.backend.knowledge.service import import_text
from database.models import AIJob, KnowledgeDocument, SourceLog

EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
PMC_OAI = 'https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/'
RUSSIAN_SOURCES = {'grls': 'https://grls.rosminzdrav.ru/', 'minzdrav': 'https://cr.minzdrav.gov.ru/'}


def log(db, source, status, message):
    db.add(SourceLog(source=source, status=status, message=message[:1500]))


def xml_text(element):
    return ' '.join(element.itertext()).strip() if element is not None else ''


def bounded_get(client, url, **kwargs):
    # Official APIs occasionally return an HTML access error with status 200.
    with client.stream('GET', url, **kwargs) as response:
        response.raise_for_status()
        content = bytearray()
        for piece in response.iter_bytes():
            content.extend(piece)
            if len(content) > 4_000_000:
                raise ValueError('Ответ источника превышает лимит 4 МБ')
        return bytes(content)


def fetch_pmc_open_text(client, pmcid):
    """OAI returns full text only for articles that permit redistribution.

    Additionally require an explicit Creative Commons/CC0 license. If no
    reusable text is returned, retain only the PubMed bibliographic metadata.
    """
    body = bounded_get(client, PMC_OAI, params={
        'verb': 'GetRecord', 'identifier': 'oai:pubmedcentral.nih.gov:' + pmcid.removeprefix('PMC'),
        'metadataPrefix': 'pmc',
    })
    root = ET.fromstring(body)
    article = next((node for node in root.iter() if node.tag.split('}')[-1] == 'article'), None)
    if article is None:
        return None
    licenses = [node for node in article.iter() if node.tag.split('}')[-1] == 'license']
    license_text = ' '.join(xml_text(node) + ' ' + ' '.join(node.attrib.values()) for node in licenses)
    if not any(term in license_text.lower() for term in ('creativecommons.org', 'creative commons', 'cc0')):
        return None
    content = []
    for node in article.iter():
        if node.tag.split('}')[-1] in {'p', 'title'}:
            paragraph = xml_text(node)
            if paragraph:
                content.append(paragraph)
    return {'text': '\n\n'.join(content), 'license': license_text[:2000]}


def sync_pubmed(db, client, maximum=8):
    params = {'db': 'pubmed', 'term': settings.pubmed_query, 'retmode': 'json',
              'retmax': min(maximum, 20), 'sort': 'pub date', 'tool': 'ClinicalCompassSynthetic'}
    if settings.pubmed_email:
        params['email'] = settings.pubmed_email
    if settings.pubmed_api_key:
        params['api_key'] = settings.pubmed_api_key
    import json
    data = json.loads(bounded_get(client, EUTILS + 'esearch.fcgi', params=params))
    identifiers = data['esearchresult']['idlist']
    # Re-fetch a rotating subset of known PMIDs as well as new publications;
    # otherwise an older paper's corrected full text would never be detected.
    known = list(db.scalars(select(KnowledgeDocument.external_id).where(
        KnowledgeDocument.source == 'pubmed').distinct().order_by(KnowledgeDocument.external_id)))
    if known:
        bucket = int(utcnow().timestamp() // (max(1, settings.knowledge_sync_hours) * 3600))
        offset = (bucket * 12) % len(known)
        rotated = known[offset:] + known[:offset]
        identifiers = list(dict.fromkeys([*identifiers, *rotated[:12]]))[:32]
    if not identifiers:
        log(db, 'pubmed', 'ok', 'По заданному запросу нет публикаций')
        return 0
    time.sleep(0.36)  # Below NCBI's unauthenticated three requests/second limit.
    fetch_params = {k: v for k, v in params.items() if k in {'email', 'api_key', 'tool'}}
    fetch_params.update(db='pubmed', id=','.join(identifiers), retmode='xml')
    root = ET.fromstring(bounded_get(client, EUTILS + 'efetch.fcgi', params=fetch_params))
    count = 0
    for article in root.findall('.//PubmedArticle'):
        pmid = article.findtext('.//PMID')
        title = xml_text(article.find('.//ArticleTitle'))
        if not pmid or not title:
            continue
        journal = xml_text(article.find('.//Journal/Title'))
        published = xml_text(article.find('.//PubDate'))
        ids = {node.attrib.get('IdType'): xml_text(node) for node in article.findall('.//ArticleId')}
        mesh = [xml_text(node) for node in article.findall('.//MeshHeading/DescriptorName')]
        metadata = {'pmid': pmid, 'doi': ids.get('doi'), 'pmcid': ids.get('pmc'),
                    'journal': journal, 'mesh': mesh, 'content_type': 'bibliographic_metadata'}
        # PubMed access alone does not grant redistribution rights to an abstract.
        text = f'{title}\nЖурнал: {journal}\nДата: {published}\nТемы: {", ".join(mesh)}'
        if ids.get('pmc'):
            try:
                time.sleep(0.36)
                opened = fetch_pmc_open_text(client, ids['pmc'])
                if opened and opened['text']:
                    text = opened['text']
                    metadata.update(content_type='open_full_text', license=opened['license'])
            except (httpx.HTTPError, ValueError, ET.ParseError):
                log(db, 'pubmed', 'partial', f'PMID {pmid}: открытый текст PMC недоступен, сохранена библиография')
        _, created = import_text(db, source='pubmed', external_id=pmid, title=title,
                                 url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
                                 category='publication', text=text, published_at=published, metadata=metadata)
        count += int(created)
    log(db, 'pubmed', 'ok', f'Проверено {len(identifiers)}, новых версий {count}; запрос: {settings.pubmed_query[:300]}')
    return count


def diagnose_russian_source(db, source, client):
    url = RUSSIAN_SOURCES[source]
    try:
        with client.stream('GET', url) as response:
            status = response.status_code
            body = next(response.iter_text(), '')[:100_000].lower()
        if status >= 400:
            message = f'Сайт отвечает HTTP {status}'
        elif any(word in body for word in ('captcha', 'капч', 'access denied')):
            message = 'Обнаружено ограничение автоматического доступа'
        else:
            message = 'Сайт доступен; стабильный документированный API массовой загрузки инструкций/рекомендаций не настроен'
        log(db, source, 'manual_import_required', message + '. Используйте импорт разрешённого локального PDF/TXT с официальной ссылкой; ограничения не обходятся.')
    except httpx.HTTPError as exc:
        log(db, source, 'unavailable', f'Источник недоступен ({type(exc).__name__}); доступен локальный импорт PDF/TXT')


def sync_sources(db, client=None):
    own_client = client is None
    client = client or httpx.Client(timeout=35, follow_redirects=True, headers={'User-Agent': 'ClinicalCompassSynthetic/0.1'})
    try:
        for source in RUSSIAN_SOURCES:
            diagnose_russian_source(db, source, client)
        try:
            sync_pubmed(db, client)
        except (httpx.HTTPError, ValueError, KeyError, ET.ParseError) as exc:
            log(db, 'pubmed', 'error', f'Официальный API недоступен или ответ некорректен ({type(exc).__name__})')
    finally:
        if own_client:
            client.close()


def schedule_sync(db):
    """Called by worker; persisted time buckets make restarts and replicas safe."""
    interval = settings.knowledge_sync_hours
    if interval <= 0:
        return None
    bucket = int(utcnow().timestamp() // (interval * 3600))
    # Do not add another sync while a previous bucket is still queued/running.
    pending = db.scalar(select(AIJob).where(AIJob.kind == 'sync', AIJob.status.in_(['pending', 'running'])).limit(1))
    return pending or enqueue(db, kind='sync', dedupe_key=f'source-sync:{bucket}')
