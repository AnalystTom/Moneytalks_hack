from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import env
from app.routers import council, demo, health, ingest, voice

app = FastAPI(title="Council")
app.add_middleware(CORSMiddleware, allow_origins=env("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
for r in (health, ingest, council, voice):
    app.include_router(r.router, prefix="/api")
app.include_router(demo.router)  # GET /demo: server-only demo page


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/demo")
