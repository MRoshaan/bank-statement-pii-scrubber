from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Batch, StatementFile, Transaction
from app.schemas import (
    BatchDetail,
    BatchSummary,
    FileOut,
    FileScrubDetail,
    ScrubResultOut,
    TransactionOut,
)
from app.services.pipeline import PipelineError, process_sources
from app.services.scrubber.engine import ResidualPIIError

router = APIRouter(prefix="/api/v1/batches", tags=["batches"])


def _batch_detail(db: Session, batch: Batch) -> BatchDetail:
    summary = BatchSummary.model_validate(batch)
    transaction_count = (
        db.query(func.count(Transaction.id)).filter(Transaction.batch_id == batch.id).scalar() or 0
    )
    return BatchDetail(
        **summary.model_dump(),
        combined_text=batch.combined_text,
        files=[FileOut.model_validate(item) for item in batch.files],
        transaction_count=int(transaction_count),
    )


@router.post("", response_model=ScrubResultOut, status_code=201)
def create_batch(
    files: list[UploadFile] = File(...),
    name: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ScrubResultOut:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one file.")
    if len(files) > settings.max_files:
        raise HTTPException(status_code=413, detail=f"At most {settings.max_files} files per batch.")

    uploads: list[tuple[str, bytes]] = []
    total = 0
    for upload in files:
        content = upload.file.read()
        size = len(content)
        if size > settings.max_file_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the per-file size limit.")
        total += size
        uploads.append((upload.filename or "unnamed", content))
    if total > settings.max_total_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload exceeds the total batch size limit.")

    try:
        result = process_sources(uploads, db=db, name=name)
    except ResidualPIIError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.batch is None:
        raise HTTPException(status_code=500, detail="Batch was not persisted.")
    detail = _batch_detail(db, result.batch)
    return ScrubResultOut(
        batch=detail,
        files=[
            FileScrubDetail(
                filename=item.filename,
                format=item.format,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                page_count=item.page_count,
                scrubbed_text=item.scrubbed_text,
                redaction_counts=item.redaction_counts or {},
                warnings=item.warnings or [],
            )
            for item in result.batch.files
        ],
    )


@router.get("", response_model=list[BatchSummary])
def list_batches(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    batches = db.query(Batch).order_by(Batch.created_at.desc()).limit(limit).all()
    return [BatchSummary.model_validate(batch) for batch in batches]


@router.get("/{batch_id}", response_model=BatchDetail)
def get_batch(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return _batch_detail(db, batch)


@router.get("/{batch_id}/scrubbed", response_class=PlainTextResponse)
def download_scrubbed(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return PlainTextResponse(
        batch.combined_text,
        headers={"Content-Disposition": f'attachment; filename="{batch.id}-scrubbed.txt"'},
    )


@router.get("/{batch_id}/transactions", response_model=list[TransactionOut])
def list_transactions(
    batch_id: UUID,
    category: str | None = None,
    merchant: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    query = (
        db.query(Transaction, StatementFile.filename)
        .join(StatementFile, StatementFile.id == Transaction.file_id)
        .filter(Transaction.batch_id == batch_id)
    )
    if category:
        query = query.filter(Transaction.category == category)
    if merchant:
        query = query.filter(Transaction.merchant.ilike(f"%{merchant}%"))
    rows = (
        query.order_by(Transaction.txn_date.asc().nullslast(), Transaction.source_line.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        TransactionOut(
            **{
                key: getattr(transaction, key)
                for key in (
                    "id",
                    "txn_date",
                    "txn_time",
                    "description",
                    "merchant",
                    "category",
                    "amount",
                    "currency",
                    "direction",
                    "balance",
                    "source_line",
                )
            },
            source_file=filename,
        )
        for transaction, filename in rows
    ]


@router.delete("/{batch_id}", status_code=204)
def delete_batch(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found.")
    db.delete(batch)
    db.commit()
    return None
