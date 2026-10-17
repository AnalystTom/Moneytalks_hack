from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import env
from app.routers import council, health, ingest, voice

app = FastAPI(title="Council")
app.add_middleware(CORSMiddleware, allow_origins=env("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
for r in (health, ingest, council, voice):
    app.include_router(r.router, prefix="/api")
