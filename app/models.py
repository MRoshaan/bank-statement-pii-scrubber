from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), default="Untitled batch")
    status: Mapped[str] = mapped_column(String(32), default="scrubbed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_chars: Mapped[int] = mapped_column(Integer, default=0)
    scrubbed_chars: Mapped[int] = mapped_column(Integer, default=0)
    combined_text: Mapped[str] = mapped_column(Text, default="")
    redaction_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    files: Mapped[list[StatementFile]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="StatementFile.filename"
    )
    redactions: Mapped[list[Redaction]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="Transaction.txn_date"
    )
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="Analysis.created_at.desc()"
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ChatSession.created_at.desc()"
    )


class StatementFile(Base):
    __tablename__ = "statement_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(512))
    format: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scrubbed_text: Mapped[str] = mapped_column(Text, default="")
    redaction_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="files")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class Redaction(Base):
    __tablename__ = "redactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statement_files.id", ondelete="CASCADE"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(64))
    placeholder: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="redactions")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("statement_files.id", ondelete="CASCADE"), index=True
    )
    txn_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    txn_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), default="Other", index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(8), default="")
    direction: Mapped[str] = mapped_column(String(8), default="debit")
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="transactions")
    file: Mapped[StatementFile] = relationship(back_populates="transactions")


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1")
    status: Mapped[str] = mapped_column(String(32), default="completed")
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    markdown: Mapped[str] = mapped_column(Text, default="")
    grounding_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="analyses")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    batch: Mapped[Batch] = relationship(back_populates="chat_sessions")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    grounding: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


Index("ix_transactions_batch_category", Transaction.batch_id, Transaction.category)
Index("ix_transactions_batch_date", Transaction.batch_id, Transaction.txn_date)
Index("ix_transactions_batch_merchant", Transaction.batch_id, Transaction.merchant)
