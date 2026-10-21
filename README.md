[github.com/ishandutta2007/Awesome-Clinical-Decision-Support-System](https://github.com/ishandutta2007/Awesome-Clinical-Decision-Support-System)


## Как запустить приложение:

1. docker compose up -d db - запустить контейнер БД
2. docker compose ps - проверить работу БД
3. python -m uvicorn app.backend.main:app --reload - запустить сервер
4. cd app/frontend; npm run dev
