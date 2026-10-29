from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import Batch, ChatMessage, ChatSession, Transaction
from app.services.llm.analysis import latest_analysis
from app.services.llm.client import (
    GroqLLM,
    LLMError,
    LLMNotConfigured,
    LLMPrivacyError,
    ensure_safe_prompt,
    sanitize_model_data,
)
from app.services.llm.context import (
    CATEGORY_HINTS,
    allowed_numbers,
    analysis_facts,
    deterministic_chat_answer,
    rows_to_context,
    validate_chat_payload,
)
from app.services.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    build_chat_prompt,
    build_repair_prompt,
)
from app.services.scrubber.engine import scrub_text
from app.services.scrubber.residual import scan_residual


class ChatGuardrailError(RuntimeError):
    pass


class ChatPayload(BaseModel):
    answer: str = Field(min_length=1, max_length=2500)
    citations: list[str] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)
    grounded: bool = True
    refusal: str | None = None


def _question_category(question: str) -> str | None:
    lowered = question.lower()
    for keyword, category in CATEGORY_HINTS.items():
        if keyword in lowered:
            return category
    return None


def _retrieve_rows(db: Session, batch: Batch, question: str) -> list[Transaction]:
    query = db.query(Transaction).filter(Transaction.batch_id == batch.id)
    selected: list[Transaction] = []
    seen: set[UUID] = set()

    def add(rows: list[Transaction]) -> None:
        for row in rows:
            if row.id not in seen:
                seen.add(row.id)
                selected.append(row)

    category = _question_category(question)
    if category:
        add(query.filter(Transaction.category == category).limit(20).all())

    tokens = [
        token
        for token in dict.fromkeys(question.lower().replace("?", " ").replace(",", " ").split())
        if len(token) >= 3 and token not in {"how", "much", "did", "the", "and", "for", "was", "were", "what", "which", "most", "often"}
    ]
    for token in tokens[:6]:
        add(
            query.filter(
                or_(
                    Transaction.merchant.ilike(f"%{token}%"),
                    Transaction.description.ilike(f"%{token}%"),
                )
            )
            .limit(8)
            .all()
        )

    facts = batch.facts or {}
    for currency_values in facts.get("top_merchants_by_count", {}).values():
        if currency_values:
            top_merchant = currency_values[0].get("merchant")
            if top_merchant:
                add(query.filter(Transaction.merchant.ilike(f"%{top_merchant}%")).limit(6).all())

    add(query.order_by(Transaction.txn_date.desc().nullslast()).limit(6).all())
    add(query.order_by(func.abs(Transaction.amount).desc()).limit(6).all())
    return selected[:18]


def _preflight(question: str, facts: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for label, payload in (("question", question), ("facts", json.dumps(facts, ensure_ascii=False)), ("rows", json.dumps(rows, ensure_ascii=False))):
        hits = scan_residual(payload)
        if hits:
            types = ", ".join(sorted({str(item["entity_type"]) for item in hits}))
            raise ChatGuardrailError(f"Residual PII detected in chat {label}: {types}")


def _fallback_or_raise(
    db: Session,
    session: ChatSession,
    question: str,
    facts: dict[str, Any],
    reason: str,
) -> tuple[ChatMessage, dict[str, Any]]:
    fallback = deterministic_chat_answer(question, facts)
    if fallback is None:
        answer = "I don't have enough grounded data to answer that from this statement. Try asking about spending, merchants, categories, fees, transfers, cash, or income."
        payload = {
            "answer": answer,
            "citations": [],
            "figures": [],
            "grounded": False,
            "refusal": "Not enough grounded context.",
        }
        model = "deterministic"
        report = {"grounded": False, "source": "refusal", "reason": reason, "checked_at": datetime.now(UTC).isoformat()}
    else:
        payload = {
            "answer": fallback["answer"],
            "citations": fallback.get("citations", []),
            "figures": [],
            "grounded": True,
            "refusal": None,
        }
        model = "deterministic"
        report = {"grounded": True, "source": "deterministic", "reason": reason, "checked_at": datetime.now(UTC).isoformat()}
    payload = sanitize_model_data(payload)
    message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=payload["answer"],
        citations=payload["citations"],
        grounding=report,
        model=model,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message, payload


def chat(db: Session, batch: Batch, message: str, session_id: UUID | None = None) -> tuple[ChatSession, ChatMessage, dict[str, Any]]:
    scrubbed_question = scrub_text(message)
    if scrubbed_question.residual:
        raise ChatGuardrailError("Your message still contains an identifier after local scrubbing; please remove it and try again.")
    question = scrubbed_question.text.strip()
    if not question:
        raise ChatGuardrailError("Message is empty after scrubbing.")

    if session_id:
        session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.batch_id == batch.id).first()
        if session is None:
            raise ValueError("Chat session not found for this batch.")
    else:
        session = ChatSession(batch_id=batch.id, title=question[:80])
        db.add(session)
        db.flush()

    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(6)
        .all()
    )
    history = [
        {"role": row.role, "content": row.content[:600]}
        for row in reversed(history_rows)
    ]
    user_message = ChatMessage(session_id=session.id, role="user", content=question)
    db.add(user_message)
    db.flush()

    records = list(batch.transactions)
    facts = analysis_facts(batch.facts or {}, records)
    category = _question_category(question)
    if category:
        facts["requested_category"] = {
            "category": category,
            "by_currency": {
                currency: values[category]
                for currency, values in ((batch.facts or {}).get("by_category") or {}).items()
                if category in values
            },
        }
    rows = _retrieve_rows(db, batch, question)
    row_context = rows_to_context(rows, limit=18)
    _preflight(question, facts, row_context)

    analysis = latest_analysis(db, batch.id)
    if analysis:
        analysis_payload = {
            key: analysis.result.get(key)
            for key in (
                "summary",
                "insights",
                "anomalies",
                "recommendations",
                "data_quality_notes",
            )
        }
    else:
        analysis_payload = {"summary": "No analysis has been generated yet."}
    valid_refs = {(record.meta or {}).get("ref") for record in records}
    valid_refs.discard(None)
    allowed = allowed_numbers(batch.facts or {}, records)

    prompt = build_chat_prompt(analysis_payload, facts, row_context, history, question)
    payload: ChatPayload | None = None
    validation: dict[str, Any] = {}
    model_used = ""
    last_errors: dict[str, Any] = {}
    llm_error: str | None = None

    try:
        llm = GroqLLM()
    except LLMNotConfigured as exc:
        llm = None
        llm_error = str(exc)

    if llm is not None:
        for attempt in range(2):
            call_prompt = prompt if attempt == 0 else build_repair_prompt(prompt, last_errors)
            try:
                ensure_safe_prompt(CHAT_SYSTEM_PROMPT, call_prompt)
            except LLMPrivacyError as exc:
                raise ChatGuardrailError(str(exc)) from exc
            try:
                result = llm.complete_json(
                    system=CHAT_SYSTEM_PROMPT,
                    user=call_prompt,
                    max_tokens=1200,
                )
                model_used = result.model
                payload = ChatPayload.model_validate(sanitize_model_data(result.data))
                validation = validate_chat_payload(payload.model_dump(), valid_refs, allowed)
                validation["checked_at"] = datetime.now(UTC).isoformat()
                if validation["grounded"]:
                    break
                last_errors = {
                    "invalid_refs": validation.get("invalid_refs", []),
                    "unsupported_numbers": validation.get("unsupported_numbers", []),
                    "invalid_figures": validation.get("invalid_figures", []),
                }
            except (ValidationError, LLMError) as exc:
                last_errors = {"error": f"Invalid model response ({type(exc).__name__})."}
                validation = {
                    "grounded": False,
                    "error": f"Invalid model response ({type(exc).__name__}).",
                    "checked_at": datetime.now(UTC).isoformat(),
                }
    else:
        validation = {"grounded": False, "error": llm_error, "checked_at": datetime.now(UTC).isoformat()}

    if payload is None or not validation.get("grounded"):
        assistant, response_payload = _fallback_or_raise(
            db,
            session,
            question,
            batch.facts or {},
            llm_error or "The model answer failed grounding validation.",
        )
        if payload is None:
            return session, assistant, response_payload
        # Keep a validated LLM answer only when it passed; otherwise use fallback.
        return session, assistant, response_payload

    safe_answer = scrub_text(payload.answer)
    if safe_answer.residual:
        assistant = ChatMessage(
            session_id=session.id,
            role="assistant",
            content="I can't include that content because it contains an identifier. Please ask a different question.",
            citations=[],
            grounding={"grounded": False, "source": "pii_guardrail", "checked_at": datetime.now(UTC).isoformat()},
            model=model_used,
        )
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        return session, assistant, {
            "answer": assistant.content,
            "citations": [],
            "figures": [],
            "grounded": False,
            "refusal": "Potential identifier in model output.",
        }

    answer = safe_answer.text
    citations = [ref for ref in payload.citations if ref in valid_refs]
    figures = [figure for figure in payload.figures if isinstance(figure, dict)]
    report = {
        **validation,
        "source": "groq",
        "refusal": payload.refusal,
    }
    assistant = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        citations=citations,
        grounding=report,
        model=model_used,
    )
    db.add(assistant)
    session.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(assistant)
    return session, assistant, {
        "answer": answer,
        "citations": citations,
        "figures": figures,
        "grounded": bool(validation.get("grounded")),
        "refusal": payload.refusal,
    }
