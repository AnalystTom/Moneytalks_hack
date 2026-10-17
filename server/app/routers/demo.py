"""Server-only demo page (GET /demo), separate from the product web app."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import COUNCIL_DIR

router = APIRouter(prefix="/demo", include_in_schema=False)
PAGE = COUNCIL_DIR.parent / "demo" / "index.html"
DATA = COUNCIL_DIR.parent.parent / "data"
FILES = {"portfolio.json": "application/json", "PERSONA.md": "text/markdown"}  # demo user Jordan, read-only


@router.get("")
async def page() -> FileResponse:
    return FileResponse(PAGE, media_type="text/html")


@router.get("/data/{name}")
async def data(name: str) -> FileResponse:
    if name not in FILES or not (DATA / name).is_file():
        raise HTTPException(404, "not a demo file")
    return FileResponse(DATA / name, media_type=FILES[name])
