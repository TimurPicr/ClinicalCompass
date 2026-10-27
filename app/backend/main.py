from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.backend.api import auth, patients, questionnaires, recommendations, alerts, treatments, followup, diary
from app.backend.core.config import settings

app = FastAPI(title="Clinical Compass", description="Демонстрационная CDSS: решения принимает врач", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Content-Type", "X-CSRF-Token"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (origin and origin not in settings.allowed_origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "Недопустимый источник запроса"})
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


for router in (auth.router, patients.router, questionnaires.router, recommendations.router,
               alerts.router, treatments.router, followup.router, diary.router):
    app.include_router(router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
