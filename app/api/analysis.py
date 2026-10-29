from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Batch
from app.schemas import AnalysisOut
from app.services.llm.analysis import GuardrailError, generate_analysis, latest_analysis
from app.services.llm.client import LLMError, LLMNotConfigured

router = APIRouter(prefix="/api/v1/batches", tags=["analysis"])


@router.post("/{batch_id}/analyze", response_model=AnalysisOut, status_code=201)
def analyze_batch(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        analysis = generate_analysis(db, batch)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=f"Groq is not configured: {exc}") from exc
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=f"Analysis blocked by guardrail: {exc}") from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Groq request failed: {exc}") from exc
    return AnalysisOut.model_validate(analysis)


@router.get("/{batch_id}/analysis", response_model=AnalysisOut)
def get_latest_analysis(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    analysis = latest_analysis(db, batch_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="No analysis exists for this batch.")
    return AnalysisOut.model_validate(analysis)
