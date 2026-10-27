"""FastAPI application; a single process also serves the built React SPA."""
import secrets
from app.backend import logging_utils  # configure token redaction
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from app.backend.config import settings
from app.backend.auth import router as auth_router

app=FastAPI(title='Clinical Compass',version='0.1.0',description='Локальный MVP для синтетических пациентов')
app.add_middleware(CORSMiddleware,allow_origins=settings.origins,allow_credentials=True,
                   allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],allow_headers=['Content-Type','X-CSRF-Token'])

@app.middleware('http')
async def security(request:Request,call_next):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        cookie=request.cookies.get('cc_csrf','')
        header=request.headers.get('X-CSRF-Token','')
        if origin and origin not in settings.origins:
            return JSONResponse({'detail':'Недопустимый источник запроса'},status_code=403)
        if not cookie or not secrets.compare_digest(cookie,header):
            return JSONResponse({'detail':'Недействительный CSRF-токен. Обновите страницу'},status_code=403)
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>(settings.max_upload_mb+1)*1024*1024):
            return JSONResponse({'detail':'Файл слишком большой'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else response.headers.get('Cache-Control','no-cache')
    if settings.cookie_secure:
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

app.include_router(auth_router)

@app.get('/api/health')
def health():
    return {'status':'ok','synthetic_only':True}

# Feature routers are registered below after their independent module tests.
from app.backend.clinical import router as clinical_router
from app.backend.ai.router import router as ai_router
from app.backend.knowledge.router import router as knowledge_router
from app.backend.documents import router as documents_router
from app.backend.chat import router as chat_router
from app.backend.notifications import router as notifications_router
for feature in (clinical_router, ai_router, knowledge_router, documents_router, chat_router, notifications_router):
    app.include_router(feature)

@app.get('/{path:path}',include_in_schema=False)
def frontend(path:str):
    if path.startswith(('api/','ws/')):
        raise HTTPException(404,'Ресурс не найден')
    root=Path(settings.frontend_dist).resolve()
    file=(root/path).resolve()
    if file.is_relative_to(root) and file.is_file():
        return FileResponse(file)
    index=root/'index.html'
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404,'Сначала запустите frontend через Vite или выполните npm run build')
