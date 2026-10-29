from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.models import Analysis, Batch
from app.services.llm.client import GroqLLM, LLMError, LLMNotConfigured
from app.services.llm.context import (
    allowed_numbers,
    analysis_facts,
    compact_facts,
    deterministic_analysis,
    ground_citations,
    markdown_from_result,
    transaction_digest,
    validate_payload,
)
from app.services.llm.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    build_analysis_prompt,
    build_repair_prompt,
)
from app.services.scrubber.residual import scan_residual


class GuardrailError(RuntimeError):
    pass


class Insight(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class Anomaly(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"


class Recommendation(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(default_factory=list)


class AnalysisPayload(BaseModel):
    summary: str = Field(min_length=1, max_length=1600)
    insights: list[Insight] = Field(min_length=1, max_length=8)
    anomalies: list[Anomaly] = Field(default_factory=list, max_length=5)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=6)
    data_quality_notes: list[str] = Field(default_factory=list, max_length=6)


def _preflight(scrubbed_text: str, facts: dict[str, Any]) -> None:
    hits = scan_residual(scrubbed_text)
    if hits:
        types = ", ".join(sorted({str(item["entity_type"]) for item in hits}))
        raise GuardrailError(f"Residual PII detected before LLM call: {types}")
    facts_text = json.dumps(facts, ensure_ascii=False)
    hits = scan_residual(facts_text)
    if hits:
        types = ", ".join(sorted({str(item["entity_type"]) for item in hits}))
        raise GuardrailError(f"Residual PII detected in facts before LLM call: {types}")


def _payload_data(payload: AnalysisPayload) -> dict[str, Any]:
    return payload.model_dump()


def _result_payload(
    payload: AnalysisPayload,
    facts: dict[str, Any],
    validation: dict[str, Any],
    model: str,
    source: str,
) -> dict[str, Any]:
    return {
        "summary": payload.summary,
        "insights": [item.model_dump() for item in payload.insights],
        "anomalies": [item.model_dump() for item in payload.anomalies],
        "recommendations": [item.model_dump() for item in payload.recommendations],
        "data_quality_notes": payload.data_quality_notes,
        "facts": compact_facts(facts),
        "validation": validation,
        "model": model,
        "source": source,
    }


def generate_analysis(db: Session, batch: Batch) -> Analysis:
    if not batch.combined_text.strip():
        raise GuardrailError("Batch has no scrubbed text.")
    facts = batch.facts or {}
    _preflight(batch.combined_text, facts)

    records = list(batch.transactions)
    valid_refs = {(record.meta or {}).get("ref") for record in records}
    valid_refs.discard(None)
    allowed = allowed_numbers(facts, records)
    compact = analysis_facts(facts, records)
    prompt = build_analysis_prompt(compact, batch.combined_text, transaction_digest(records))

    try:
        llm = GroqLLM()
    except LLMNotConfigured:
        raise
    payload: AnalysisPayload | None = None
    model_used = ""
    usage: dict[str, Any] = {}
    last_errors: dict[str, Any] = {}
    for attempt in range(2):
        try:
            result = llm.complete_json(
                system=ANALYSIS_SYSTEM_PROMPT,
                user=prompt if attempt == 0 else build_repair_prompt(prompt, last_errors),
                max_tokens=1200,
            )
            model_used = result.model
            usage = result.usage
            payload = AnalysisPayload.model_validate(result.data)
            grounded_data = ground_citations(_payload_data(payload), facts, records)
            payload = AnalysisPayload.model_validate(grounded_data)
            validation = validate_payload(_payload_data(payload), valid_refs, allowed)
            validation["checked_at"] = datetime.now(UTC).isoformat()
            if validation["grounded"]:
                break
            last_errors = {
                "invalid_refs": validation["invalid_refs"],
                "unsupported_numbers": validation["unsupported_numbers"],
            }
        except (ValidationError, LLMError) as exc:
            last_errors = {"error": str(exc)[:800]}
            validation = {
                "grounded": False,
                "invalid_refs": [],
                "unsupported_numbers": [],
                "error": str(exc)[:800],
                "checked_at": datetime.now(UTC).isoformat(),
            }

    if payload is None:
        fallback = deterministic_analysis(facts)
        payload = AnalysisPayload.model_validate(fallback)
        validation = {
            "grounded": True,
            "source": "deterministic_fallback",
            "invalid_refs": [],
            "unsupported_numbers": [],
            "checked_at": datetime.now(UTC).isoformat(),
        }
        model_used = "deterministic"
        status = "fallback"
    else:
        status = "completed" if validation.get("grounded") else "needs_review"

    result_payload = _result_payload(payload, facts, validation, model_used, "groq" if model_used != "deterministic" else "deterministic")
    markdown = markdown_from_result(result_payload)
    analysis = Analysis(
        batch_id=batch.id,
        model=model_used or "unknown",
        prompt_version="analysis-v1",
        status=status,
        result=result_payload,
        markdown=markdown,
        grounding_report=validation,
        usage=usage,
        error=None if status == "completed" else json.dumps(last_errors)[:2000] if last_errors else None,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def latest_analysis(db: Session, batch_id) -> Analysis | None:
    return (
        db.query(Analysis)
        .filter(Analysis.batch_id == batch_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
