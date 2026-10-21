from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.api.questionnaires import (
    router as questionnaire_router,
)

from app.backend.api.recommendations import (
    router as recommendations_router,
)


app = FastAPI(
    title="Clinical Compass",
    description="Цифровой помощник врача",
    version="0.1.0",
)


app.include_router(recommendations_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(questionnaire_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}