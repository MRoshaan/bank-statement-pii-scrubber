from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import analysis, batches, chat, health
from app.db import create_all

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(
    title="PJ Bank API",
    description="Local PII scrubber, PostgreSQL store, and grounded Groq budgeting assistant.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(batches.router)
app.include_router(analysis.router)
app.include_router(chat.router)

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")
