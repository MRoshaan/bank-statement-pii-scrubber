from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FileOut(BaseModel):
    id: UUID
    filename: str
    format: str
    size_bytes: int
    sha256: str
    page_count: int | None
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BatchSummary(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    file_count: int
    raw_chars: int
    scrubbed_chars: int
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BatchDetail(BatchSummary):
    combined_text: str
    files: list[FileOut] = Field(default_factory=list)
    transaction_count: int = 0


class FileScrubDetail(BaseModel):
    filename: str
    format: str
    size_bytes: int
    sha256: str
    page_count: int | None
    scrubbed_text: str
    redaction_counts: dict[str, int]
    warnings: list[str]


class ScrubResultOut(BaseModel):
    batch: BatchDetail
    files: list[FileScrubDetail]


class TransactionOut(BaseModel):
    id: UUID
    txn_date: date | None
    txn_time: str | None
    description: str
    merchant: str | None
    category: str
    amount: Decimal
    currency: str
    direction: str
    balance: Decimal | None
    source_file: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AnalysisOut(BaseModel):
    id: UUID
    batch_id: UUID
    model: str
    prompt_version: str
    status: str
    result: dict[str, Any]
    markdown: str
    grounding_report: dict[str, Any]
    usage: dict[str, Any]
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None


class ChatMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list[Any] = Field(default_factory=list)
    grounding: dict[str, Any] = Field(default_factory=dict)
    model: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    citations: list[Any] = Field(default_factory=list)
    grounded: bool = False
    grounding: dict[str, Any] = Field(default_factory=dict)
    model: str


class ChatSessionOut(BaseModel):
    id: UUID
    batch_id: UUID
    title: str
    created_at: datetime
    messages: list[ChatMessageOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    database: str
    groq_configured: bool
    model: str
