from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas import HealthOut

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health endpoint should report, not raise
        database = "unavailable"
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        database=database,
        groq_configured=bool(settings.groq_api_key),
        model=settings.groq_model,
    )
