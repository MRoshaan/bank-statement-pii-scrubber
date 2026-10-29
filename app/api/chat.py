from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Batch, ChatSession
from app.schemas import ChatMessageOut, ChatRequest, ChatResponse, ChatSessionOut
from app.services.llm.chat import ChatGuardrailError, chat
from app.services.llm.client import LLMError, LLMNotConfigured

router = APIRouter(prefix="/api/v1/batches", tags=["chat"])


@router.post("/{batch_id}/chat", response_model=ChatResponse)
def chat_with_batch(batch_id: UUID, body: ChatRequest, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    try:
        session, message, payload = chat(db, batch, body.message, body.session_id)
    except ChatGuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=f"Groq is not configured: {exc}") from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"Groq request failed: {exc}") from exc
    return ChatResponse(
        session_id=session.id,
        answer=payload["answer"],
        citations=payload.get("citations", []),
        grounded=bool(payload.get("grounded")),
        grounding=message.grounding or {},
        model=message.model or "",
    )


@router.get("/{batch_id}/chat/sessions/{session_id}", response_model=ChatSessionOut)
def get_chat_session(batch_id: UUID, session_id: UUID, db: Session = Depends(get_db)):
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.batch_id == batch_id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return ChatSessionOut(
        id=session.id,
        batch_id=session.batch_id,
        title=session.title,
        created_at=session.created_at,
        messages=[ChatMessageOut.model_validate(message) for message in session.messages],
    )


@router.get("/{batch_id}/chat/sessions", response_model=list[ChatSessionOut])
def list_chat_sessions(batch_id: UUID, db: Session = Depends(get_db)):
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.batch_id == batch_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(20)
        .all()
    )
    return [
        ChatSessionOut(
            id=session.id,
            batch_id=session.batch_id,
            title=session.title,
            created_at=session.created_at,
            messages=[],
        )
        for session in sessions
    ]
