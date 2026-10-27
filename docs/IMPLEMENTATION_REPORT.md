# Отчёт о реализации Clinical Compass

Актуальная перепроверка: [23 октября 2026](RECHECK_2026-10-23.md). Текущий стенд: http://localhost:5173; прежний временный стенд 5174 из описания ниже относится к прошлой проверке.

Дата: 22 октября 2026, Europe/Moscow. Репозиторий изменён непосредственно; коммит не создавался. Исходные пользовательские `.env` и данные прежнего PostgreSQL не изменялись. Архитектура `app/backend`, `app/database`, `app/frontend`, `tests` сохранена.

## 1. Реально реализованные функции

- Регистрация только пациентов, вход по email, Argon2id, JWT в HttpOnly cookie, серверная проверка и отзыв сессий, CSRF и Origin. Создание врача — контролируемая CLI с вводом пароля без отображения.
- Один ведущий врач, email-привязанные приглашения на 48 часов, отправка SMTP и автоматическое принятие ссылки после входа пациентом. Токен не возвращается врачу в API. Для локальной проверки используется Mailpit; внешняя доставка требует SMTP-реквизитов. Проверка доступа к каждому медицинскому ресурсу и вложенному идентификатору.
- Сохранение ответов, баллов, шкалы/версии и времени. Прежний алгоритм подсчёта сохранён. Реестр версионируемых определений и scorer-ов; PHQ-9/GAD-7 неактивны.
- История, фильтры шкалы/версии/периода, независимые временные ряды и графики SVG. Календарь пациента объединяет фиксированные вопросы прежнего опросника со свободными заметками; одна запись на дату, редактирование сохраняет версии. График календаря использует дату записи и последнюю редакцию ответов, свободный текст не оценивается.
- Явный срочный запрос, предупреждение о нежелательном явлении, критичность, врач-получатель, подтверждение, история, ключ дедупликации и журнал доступности в веб-кабинете. Добавлены конфигурируемые клинические правила с проверкой экспертного статуса; активных клинических правил в поставке нет.
- Существующий модуль учебных рекомендаций интегрирован с результатами и PostgreSQL; история, объяснения, источник и версия, принятие/отклонение с комментарием. Для существующего `recomendation.py` есть отключённый по умолчанию HTTP-адаптер с сохранением PDF-источников/страниц. Второго движка нет.
- Справочник лекарств с источником ГРЛС, регистрацией, показаниями, противопоказаниями, режимами и отдельной ручной проверкой врача. «Авиандр» — неполная заблокированная заготовка. Назначения хранят снимок проверенной записи.
- Неизменяемые версии плана, черновик, отдельное подтверждение врача, архив предыдущих версий; пациент не видит черновиков. Принятие рекомендации не назначает терапию.
- Самоотчёты о выполнении/пропуске/частичном выполнении и агрегат, история нежелательных явлений и рассмотрение врачом, REST-чат с ограничением по связи врача/пациента, автоматическим опросом новых сообщений каждые 2 секунды, переподключением и сохранением неотправленного текста.
- Кабинеты React с отдельными компонентами и API-клиентом, загрузкой, пустыми/ошибочными состояниями, подтверждениями действий, адаптивными стилями. Кнопки обновления истории и предупреждений; переход из предупреждения к пациенту. У пациента убраны технические сведения, общий баннер о прототипе, версии шкал и служебные сведения о лекарствах.
- Пять миграций Alembic, сервисы приложения и локальная почта Mailpit в Compose, healthchecks и применение миграций при запуске, persistent volume, `.env.example`, инструкции backup/restore.

## 2–3. Файлы и назначение

Полный перечень новых и изменённых файлов приведён в конце этого отчёта. Основные группы:

| Группа | Назначение |
| --- | --- |
| `api/auth.py`, `core/security.py`, `cli.py` | Сессии, роли, CSRF, права и создание врача |
| `api/patients.py` | Подтверждаемая привязка и карточка |
| `models/clinical.py`, `schemas/clinical.py` | Сущности процессов и проверка ввода |
| `services/scales.py`, `api/questionnaires.py` | Версионирование шкал, сохранение и мониторинг |
| `api/recommendations.py`, `services/recommendations/rag_adapter.py` | Интеграция прежних правил/RAG и рассмотрение |
| `api/alerts.py`, `services/workflows.py`, `services/alert_rules.py` | События, аудит, дедупликация и проверенные правила |
| `api/treatments.py`, `api/followup.py` | Справочник, планы, самоотчёты, события и чат |
| `core/time.py` | UTC-временные границы, московский день самоотчёта |
| `app/database/migrations/versions/*.py` | Схема, безопасные заготовки справочников, происхождение RAG и правила |
| `app/frontend/src/pages/`, `components/`, `api.ts`, `types.ts`, `format.ts` | Разделённый интерфейс и API-клиент |
| `tests/`, `workflows.test.tsx`, `vitest.config.ts` | Изолированные API, PostgreSQL и React-проверки |
| Dockerfiles, Compose, Nginx, dockerignore | Воспроизводимый локальный стенд |
| `README.md`, `docs/AUDIT.md` | Русская инструкция и исходный аудит |

Существующие модуль подсчёта, генератор/правила рекомендаций, корневые прототипы и RAG-движок не переписаны. POST учебного опроса теперь требует пациента, preview рекомендаций — врача; это необходимое изменение защиты. Прежние тесты сохранены по смыслу и адаптированы к авторизованным клиентам и временной БД.

## 4. Команды запуска

Для основного стенда из корня:

```bash
cp -n .env.example .env
python3 -c 'import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))'
```

Внесите значения в `.env`, как описано в README. Существующий файл не перезаписывайте; добавьте недостающие настройки, согласованные с реальными реквизитами существующего тома PostgreSQL.

```bash
docker compose up -d --build --wait
docker compose exec backend python -m app.backend.cli create-doctor --email doctor@example.com --name "Демонстрационный врач"
```

Основной интерфейс: http://localhost:5173. Пароль врача вводится интерактивно. Подробный ручной сценарий и запуск без Docker — в README.

В ходе проверки также создан отдельный стенд `clinical-compass-demo-check`: http://localhost:5174, backend 8002, PostgreSQL 55433. Он использует отдельный том и конфигурацию `/private/tmp/clinical-compass-demo-check.env`; это временная проверочная конфигурация, а не изменение пользовательского `.env`. В нём только синтетические записи. Для собственного врача в этом стенде:

```bash
docker compose -p clinical-compass-demo-check --env-file /private/tmp/clinical-compass-demo-check.env exec backend python -m app.backend.cli create-doctor --email reviewer@example.com --name "Проверяющий врач"
```

## 5. Выполненные проверки

| Проверка | Результат |
| --- | --- |
| Исходные тесты до изменений | 8 passed |
| Итоговый backend на временной SQLite | 52 passed, 3 PostgreSQL-only skipped |
| Итоговый backend на PostgreSQL 16 | 55 passed |
| Backend внутри собранного Python 3.12-образа | 52 passed, 3 PostgreSQL-only skipped |
| React/Vitest/Testing Library | 16 passed |
| TypeScript + Vite production build | Пройдена локально и в Docker/Node 24 |
| ESLint | Пройден |
| Python compileall, `sh -n run.sh`, `git diff --check` | Пройдены |
| Alembic | Миграции на каждой временной БД; PostgreSQL upgrade/downgrade/upgrade и `alembic check` без расхождений |
| PostgreSQL-конкурентность | Параллельные одинаковые алерты дают одну запись/одну попытку; версии планов сериализуются блокировкой пациента |
| Docker Compose | Образы собраны, PostgreSQL и backend healthy, frontend запущен; исходный стенд не затрагивался |
| Реальный HTTP через Nginx | Регистрация, вход, приглашение, 2 результата/ряд, рассмотрение предложения, алерт/ack, черновик/подтверждение, самоотчёт, нежелательное явление/рассмотрение, двусторонний чат прошли |
| Перезапуск Docker | Результаты, план, отчёт, событие, сообщения и алерты сохранились; проверено повторным входом через Nginx |
| Backup/restore | `pg_dump -Fc`, восстановление в отдельную пустую `clinical_compass_restore_test`; в копии 2 результата и 2 сообщения |

В backend-тестах остаётся предупреждение Starlette об устаревающем httpx TestClient; это предупреждение зависимости, падений нет. Тесты никогда не подключаются к рабочей `.env`-БД. Подробные команды — в README.

## 6. Ограничения

- Визуальная браузерная приёмка не выполнена: доступные браузеры в сессии отсутствуют. Проверены React-компоненты, сборка и реальный API через Nginx.
- Реальные Ollama/LLM/Qdrant и PDF-корпус не запускались. Проверены контракт и сохранение RAG-ответа с заглушкой; адаптер по умолчанию отключён.
- Нет подтверждённых русских версий PHQ-9/GAD-7, клинических порогов или сведений о препаратах; их содержимое не выдумывалось. Полный лекарственный сценарий проверен только с синтетической записью в изолированном тесте, без утверждений о реальной терапии.
- Проверка ГРЛС — ручное подтверждение врача. Наличие правильного домена и регистрационного номера само по себе не проверяет документ.
- Алерты доступны в веб-кабинете. Фоновый доставщик, SMS/email-доставка алертов, гарантированные повторы и эскалация не реализованы. Email-приглашения отправляются отдельным SMTP-модулем. Клинические правила требуют отдельной экспертно проверенной миграции.
- Нет reset password, email verification, MFA, распределённого ограничения попыток входа, смены врача, пагинации длинных историй и внешнего защищённого от изменения аудита. Чат обновляется автоматически; алерты — вручную.
- Не выполнены медицинская/регуляторная валидация и проверка соответствия законодательству РФ. Это учебный стенд.

## 7. Следующие ручные действия

1. Согласовать `.env` с существующим PostgreSQL, сгенерировать отдельные реальные секреты для своего локального стенда, создать врача CLI.
2. Пройти сценарий README в двух профилях браузера и выполнить визуальную проверку на нужных устройствах.
3. Перед любым включением клинических шкал, правил или лекарственных сведений получить проверенный материал, источники, права использования и экспертное заключение.
4. Для реального применения отдельно спроектировать HTTPS/эксплуатацию, надёжное оповещение, защиту персональных данных, резервное копирование, управление доступом и юридическую проверку.

## Дополнение: календарь, почта и чат

Проверены новая миграция, история редактирования дневника, защита чужих записей, запрет будущих дат, фильтрация календаря и инкрементальное получение чата. React-тесты проверяют запись/график, режим врача без редактирования, принятие ссылки, отправку приглашения и автоматические обновления чата с остановкой при закрытии. На реальном Docker-стенде выполнен SMTP → Mailpit → ссылка → авторизованное прикрепление → два дня дневника/график → чат. Нажатие ссылки без защищённого POST само по себе данные не меняет.

Mailpit: http://localhost:8025; приложение: http://localhost:5174. Доставка во внешнюю почту требует SMTP-аккаунта и настройки переменных `.env`; SMTP-реквизиты не создавались и пользовательский `.env` не менялся.

Новые модули: `api/diary.py`, `services/mail.py`, модели DiaryEntry/DiaryRevision, миграция `d58e9137a024_diary_and_email.py`, компоненты DiaryCalendar/InvitationAcceptance и тесты `test_diary_mail_chat.py`/`diary-chat.test.tsx`.

## Полный перечень новых файлов

- `.dockerignore`
- `.env.example`
- `Dockerfile.backend`
- `app/backend/api/alerts.py`
- `app/backend/api/auth.py`
- `app/backend/api/diary.py`
- `app/backend/api/followup.py`
- `app/backend/api/patients.py`
- `app/backend/api/treatments.py`
- `app/backend/cli.py`
- `app/backend/core/security.py`
- `app/backend/core/time.py`
- `app/backend/models/clinical.py`
- `app/backend/schemas/clinical.py`
- `app/backend/services/alert_rules.py`
- `app/backend/services/mail.py`
- `app/backend/services/recommendations/rag_adapter.py`
- `app/backend/services/scales.py`
- `app/backend/services/workflows.py`
- `app/database/migrations/versions/6294c3b6707c_clinical_workflows.py`
- `app/database/migrations/versions/75f7c420c9a1_demo_catalog.py`
- `app/database/migrations/versions/923ffa482c11_rag_evidence.py`
- `app/database/migrations/versions/a712e69357c0_reviewed_alert_rules.py`
- `app/database/migrations/versions/d58e9137a024_diary_and_email.py`
- `app/frontend/.dockerignore`
- `app/frontend/Dockerfile`
- `app/frontend/nginx.conf`
- `app/frontend/src/api.ts`
- `app/frontend/src/components/Alerts.tsx`
- `app/frontend/src/components/Chat.tsx`
- `app/frontend/src/components/DiaryCalendar.tsx`
- `app/frontend/src/components/DoctorTools.tsx`
- `app/frontend/src/components/Followup.tsx`
- `app/frontend/src/components/Form.tsx`
- `app/frontend/src/components/InvitationAcceptance.tsx`
- `app/frontend/src/components/Monitoring.tsx`
- `app/frontend/src/components/Questionnaires.tsx`
- `app/frontend/src/components/Treatment.tsx`
- `app/frontend/src/diary-chat.test.tsx`
- `app/frontend/src/format.ts`
- `app/frontend/src/pages/AuthPage.tsx`
- `app/frontend/src/pages/Dashboard.tsx`
- `app/frontend/src/pages/Workspace.tsx`
- `app/frontend/src/test-setup.ts`
- `app/frontend/src/types.ts`
- `app/frontend/src/workflows.test.tsx`
- `app/frontend/vitest.config.ts`
- `docker-compose.test.yml`
- `docs/AUDIT.md`
- `docs/IMPLEMENTATION_REPORT.md`
- `tests/conftest.py`
- `tests/test_diary_mail_chat.py`
- `tests/test_postgresql.py`
- `tests/test_rag.py`
- `tests/test_workflows.py`

## Полный перечень изменённых файлов

- `.gitignore`
- `README.md`
- `app/backend/api/questionnaires.py`
- `app/backend/api/recommendations.py`
- `app/backend/core/config.py`
- `app/backend/main.py`
- `app/backend/models/user.py`
- `app/backend/schemas/questionnaire.py`
- `app/database/models.py`
- `app/frontend/package-lock.json`
- `app/frontend/package.json`
- `app/frontend/src/App.css`
- `app/frontend/src/App.tsx`
- `app/frontend/src/index.css`
- `app/frontend/vite.config.ts`
- `docker-compose.yml`
- `requirements.txt`
- `run.sh`
- `tests/test_questionnaires.py`
- `tests/test_recommendations.py`
