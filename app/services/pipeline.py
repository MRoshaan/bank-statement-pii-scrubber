from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Batch, Redaction, StatementFile, Transaction
from app.services.extractors import (
    ExtractedFile,
    ExtractionError,
    ExtractionLimitError,
    combine_files,
    discover_files,
    expand_zip,
    extract_bytes,
)
from app.services.facts import build_facts
from app.services.scrubber.engine import ScrubResult, scrub_text
from app.services.transactions import ParseResult, TransactionRecord, parse_transactions


class PipelineError(RuntimeError):
    pass


class UploadLimitError(PipelineError):
    pass


@dataclass
class FileResult:
    extracted: ExtractedFile
    scrub: ScrubResult | None
    parsed: ParseResult
    warnings: list[str] = field(default_factory=list)
    file_model: StatementFile | None = None


@dataclass
class PipelineResult:
    files: list[FileResult]
    records: list[TransactionRecord]
    facts: dict
    combined_text: str
    warnings: list[str]
    batch: Batch | None = None


STATEMENT_EXTENSIONS = {".pdf", ".docx", ".csv", ".txt", ".text", ".log"}


def _safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "_", base)
    suffix = Path(base).suffix
    if suffix.lower() not in STATEMENT_EXTENSIONS | {".zip"}:
        suffix = ""
    stem = base[:-len(suffix)] if suffix else base
    safe = scrub_text(stem)
    if safe.residual:
        raise PipelineError("Filename contains an identifier after scrubbing.")
    # Keep the extension for format detection and use portable placeholder names.
    stem = safe.text.translate(str.maketrans({"<": "_", ">": "_", "/": "_", "\\": "_"}))
    return (stem[:200] or "unnamed") + suffix[:16]


def _prepare_sources(uploads: Iterable[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    prepared: list[tuple[str, bytes]] = []
    used: set[str] = set()
    total = 0
    max_file = settings.max_file_mb * 1024 * 1024
    max_total = settings.max_total_mb * 1024 * 1024

    def add(name: str, data: bytes) -> None:
        nonlocal total
        if len(prepared) >= settings.max_files:
            raise UploadLimitError("Upload exceeds the batch file count limit.")
        if len(data) > max_file:
            raise UploadLimitError("A file exceeds the per-file size limit.")
        total += len(data)
        if total > max_total:
            raise UploadLimitError("Upload exceeds the total batch size limit.")
        safe_name = _safe_filename(name)
        path = Path(safe_name)
        counter = 2
        candidate = safe_name
        while candidate.casefold() in used:
            candidate = f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        used.add(candidate.casefold())
        prepared.append((candidate, data))

    for name, content in uploads:
        if len(content) > max_file:
            raise UploadLimitError("A file exceeds the per-file size limit.")
        safe_name = _safe_filename(name)
        if safe_name.lower().endswith(".zip"):
            try:
                members = expand_zip(
                    safe_name,
                    content,
                    max_files=settings.max_files - len(prepared),
                    max_file_bytes=max_file,
                    max_total_bytes=max_total - total,
                )
                for member, data in members:
                    add(member, data)
            except ExtractionLimitError as exc:
                raise UploadLimitError(str(exc)) from exc
            except ExtractionError as exc:
                raise PipelineError(str(exc)) from exc
        else:
            add(safe_name, content)
    return prepared


def _process_one(name: str, content: bytes) -> FileResult:
    try:
        extracted = extract_bytes(name, content)
    except ExtractionError as exc:
        extracted = ExtractedFile(
            filename=name,
            format="unknown",
            text="",
            size_bytes=len(content),
            sha256="",
            page_count=None,
            warnings=[str(exc)],
        )
        return FileResult(
            extracted=extracted,
            scrub=None,
            parsed=ParseResult(records=[], warnings=[str(exc)]),
            warnings=[str(exc)],
        )

    scrub = scrub_text(extracted.text)
    parsed = parse_transactions(extracted.filename, scrub.text)
    warnings = [*extracted.warnings, *scrub.warnings, *parsed.warnings]
    if scrub.residual:
        types = ", ".join(sorted({str(item["entity_type"]) for item in scrub.residual}))
        raise PipelineError(f"Residual PII detected in {extracted.filename}: {types}")
    return FileResult(extracted=extracted, scrub=scrub, parsed=parsed, warnings=warnings)


def _persist(
    db: Session,
    name: str,
    files: list[FileResult],
    records: list[TransactionRecord],
    facts: dict,
    combined_text: str,
    warnings: list[str],
) -> Batch:
    redaction_counts: dict[str, int] = {}
    for result in files:
        if result.scrub:
            for key, value in result.scrub.redaction_counts.items():
                redaction_counts[key] = redaction_counts.get(key, 0) + value

    batch = Batch(
        name=name,
        status="scrubbed",
        file_count=len(files),
        raw_chars=sum(len(result.extracted.text) for result in files),
        scrubbed_chars=sum(len(result.scrub.text) if result.scrub else 0 for result in files),
        combined_text=combined_text,
        redaction_counts=redaction_counts,
        facts=facts,
        warnings=warnings,
    )
    db.add(batch)
    db.flush()

    file_by_name: dict[str, StatementFile] = {}
    for result in files:
        file_model = StatementFile(
            batch_id=batch.id,
            filename=result.extracted.filename,
            format=result.extracted.format,
            size_bytes=result.extracted.size_bytes,
            sha256=result.extracted.sha256,
            page_count=result.extracted.page_count,
            scrubbed_text=result.scrub.text if result.scrub else "",
            redaction_counts=result.scrub.redaction_counts if result.scrub else {},
            warnings=result.warnings,
        )
        db.add(file_model)
        db.flush()
        result.file_model = file_model
        file_by_name[result.extracted.filename] = file_model

        if result.scrub:
            for finding in result.scrub.findings:
                db.add(
                    Redaction(
                        batch_id=batch.id,
                        file_id=file_model.id,
                        entity_type=str(finding["entity_type"]),
                        placeholder=str(finding["placeholder"]),
                        count=int(finding["count"]),
                    )
                )

    for record in records:
        file_model = file_by_name.get(record.filename)
        if file_model is None:
            continue
        db.add(
            Transaction(
                batch_id=batch.id,
                file_id=file_model.id,
                txn_date=record.txn_date,
                txn_time=record.txn_time,
                description=record.description,
                merchant=record.merchant,
                category=record.category,
                amount=record.amount,
                currency=record.currency,
                direction=record.direction,
                balance=record.balance,
                source_line=record.line_no,
                meta={**record.meta, "ref": record.ref},
            )
        )

    db.commit()
    db.refresh(batch)
    return batch


def process_sources(
    uploads: Iterable[tuple[str, bytes]],
    db: Session | None = None,
    name: str | None = None,
) -> PipelineResult:
    sources = _prepare_sources(uploads)
    if not sources:
        raise PipelineError("No files were provided.")
    sources.sort(key=lambda item: item[0].lower())

    files: list[FileResult] = []
    for filename, content in sources:
        files.append(_process_one(filename, content))

    successful = [result for result in files if result.scrub is not None]
    if not successful:
        details = "; ".join(result.warnings[0] if result.warnings else "extraction failed" for result in files)
        raise PipelineError(f"No files could be processed: {details}")

    combined_text = combine_files(
        [
            ExtractedFile(
                filename=result.extracted.filename,
                format=result.extracted.format,
                text=result.scrub.text if result.scrub else "[extraction failed]",
                size_bytes=result.extracted.size_bytes,
                sha256=result.extracted.sha256,
                page_count=result.extracted.page_count,
                warnings=result.warnings,
            )
            for result in files
        ]
    )
    records = [record for result in files for record in result.parsed.records]
    warnings = [warning for result in files for warning in result.warnings]
    file_summaries = [
        {
            "filename": result.extracted.filename,
            "format": result.extracted.format,
            "transactions": len(result.parsed.records),
            "warnings": result.warnings,
        }
        for result in files
    ]
    facts = build_facts(records, file_summaries, warnings)
    batch_name_result = scrub_text(name or f"Batch {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    if batch_name_result.residual:
        raise PipelineError("Batch name contains an identifier after scrubbing.")
    batch_name = batch_name_result.text.strip()[:255] or "Untitled batch"
    batch = _persist(db, batch_name, files, records, facts, combined_text, warnings) if db is not None else None
    return PipelineResult(
        files=files,
        records=records,
        facts=facts,
        combined_text=combined_text,
        warnings=warnings,
        batch=batch,
    )


def process_folder(folder: Path, db: Session | None = None, name: str | None = None) -> PipelineResult:
    paths = discover_files(folder)
    uploads = [(path.name, path.read_bytes()) for path in paths]
    return process_sources(uploads, db=db, name=name or folder.name)
