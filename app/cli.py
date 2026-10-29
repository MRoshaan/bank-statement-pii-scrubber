from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.db import SessionLocal, create_all
from app.services.pipeline import process_folder


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def scrub_command(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    per_file_dir = out_dir / "per_file"
    per_file_dir.mkdir(parents=True, exist_ok=True)

    db = None
    if args.store:
        create_all()
        db = SessionLocal()
    try:
        result = process_folder(folder, db=db, name=args.name)
    finally:
        if db is not None:
            db.close()

    combined_path = out_dir / "scrubbed_combined.txt"
    combined_path.write_text(result.combined_text, encoding="utf-8")

    used_names: set[str] = set()
    per_file_payload: list[dict[str, Any]] = []
    for file_result in result.files:
        stem = Path(file_result.extracted.filename).stem or "file"
        candidate = f"{stem}.scrubbed.txt"
        counter = 2
        while candidate in used_names:
            candidate = f"{stem}-{counter}.scrubbed.txt"
            counter += 1
        used_names.add(candidate)
        text = file_result.scrub.text if file_result.scrub else ""
        (per_file_dir / candidate).write_text(text, encoding="utf-8")
        per_file_payload.append(
            {
                "filename": file_result.extracted.filename,
                "format": file_result.extracted.format,
                "output": f"per_file/{candidate}",
                "redaction_counts": file_result.scrub.redaction_counts if file_result.scrub else {},
                "findings": file_result.scrub.findings if file_result.scrub else [],
                "warnings": file_result.warnings,
                "transactions": len(file_result.parsed.records),
            }
        )

    _write_json(
        out_dir / "redaction_report.json",
        {
            "batch_id": str(result.batch.id) if result.batch else None,
            "batch_name": result.batch.name if result.batch else args.name or folder.name,
            "files": per_file_payload,
            "totals": result.batch.redaction_counts if result.batch else {
                key: sum(item["redaction_counts"].get(key, 0) for item in per_file_payload)
                for key in sorted({key for item in per_file_payload for key in item["redaction_counts"]})
            },
            "warnings": result.warnings,
        },
    )
    _write_json(out_dir / "transactions.json", [record.to_dict() for record in result.records])
    _write_json(out_dir / "facts.json", result.facts)
    _write_json(
        out_dir / "metadata.json",
        {
            "batch_id": str(result.batch.id) if result.batch else None,
            "stored_in_postgres": result.batch is not None,
            "file_count": len(result.files),
            "transaction_count": len(result.records),
            "combined_output": "scrubbed_combined.txt",
            "per_file_output": "per_file/",
        },
    )

    print(f"Files: {len(result.files)}")
    print(f"Transactions: {len(result.records)}")
    print(f"Combined output: {combined_path}")
    print(f"Per-file output: {per_file_dir}")
    if result.batch:
        print(f"PostgreSQL batch: {result.batch.id}")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)}")
        for warning in result.warnings[:10]:
            print(f"  - {warning}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PII-safe bank statement scrubber")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scrub = subparsers.add_parser("scrub", help="Scrub every supported file in a folder")
    scrub.add_argument("folder", help="Folder containing PDF/DOCX/CSV/TXT statements")
    scrub.add_argument("--out", default="outputs", help="Output directory (default: outputs)")
    scrub.add_argument("--name", default=None, help="Batch name")
    scrub.add_argument("--store", action="store_true", help="Persist the scrubbed batch to PostgreSQL")
    scrub.set_defaults(func=scrub_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
