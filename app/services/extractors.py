from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from charset_normalizer import from_bytes
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


class ExtractionError(Exception):
    pass


class ExtractionLimitError(ExtractionError):
    pass


@dataclass
class ExtractedFile:
    filename: str
    format: str
    text: str
    size_bytes: int
    sha256: str
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


def _decode_text(content: bytes) -> tuple[str, str | None]:
    result = from_bytes(content).best()
    if result is not None:
        return str(result), None
    try:
        return content.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace"), "Text decoding used replacement characters."


def _format_for(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if content.startswith(b"%PDF") or suffix == ".pdf":
        return "pdf"
    if suffix == ".docx" or (content.startswith(b"PK") and b"word/document.xml" in content):
        return "docx"
    if suffix == ".csv":
        return "csv"
    if suffix in {".txt", ".text", ".log"}:
        return "txt"
    if b"\x00" in content[:4096]:
        raise ExtractionError(f"Unsupported binary file: {filename}")
    return "txt"


def _iter_docx_blocks(parent):
    parent_elm = parent.element.body
    for child in parent_elm.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _extract_docx(content: bytes) -> tuple[str, int | None, list[str]]:
    document = Document(io.BytesIO(content))
    lines: list[str] = []
    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            if block.text.strip():
                lines.append(block.text)
        else:
            for row in block.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    for section in document.sections:
        for container in (section.header, section.footer):
            for paragraph in container.paragraphs:
                if paragraph.text.strip() and paragraph.text not in lines:
                    lines.append(paragraph.text)
    return "\n".join(lines), None, []


def _extract_pdf(content: bytes) -> tuple[str, int | None, list[str]]:
    pages: list[str] = []
    warnings: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
            if not text.strip():
                warnings.append(f"Page {index} has no extractable text layer.")
            # pdfplumber preserves horizontal position with leading spaces; drop the
            # page margin while keeping word spacing inside each row.
            text = "\n".join(line.strip() for line in text.splitlines())
            pages.append(text.rstrip())
    if not any(page.strip() for page in pages):
        warnings.append("PDF contains no text layer. Scanned PDFs need OCR, which is not enabled.")
    return "\n\n".join(pages), len(pages), warnings


def extract_bytes(filename: str, content: bytes) -> ExtractedFile:
    safe_name = Path(filename).name or "unnamed"
    size = len(content)
    digest = hashlib.sha256(content).hexdigest()
    fmt = _format_for(safe_name, content)
    warnings: list[str] = []
    page_count: int | None = None
    try:
        if fmt == "pdf":
            text, page_count, warnings = _extract_pdf(content)
        elif fmt == "docx":
            text, page_count, warnings = _extract_docx(content)
        else:
            text, warning = _decode_text(content)
            if warning:
                warnings.append(warning)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a useful per-file error
        raise ExtractionError(f"Could not extract {safe_name} ({type(exc).__name__}).") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        warnings.append("No extractable text was found.")
    return ExtractedFile(
        filename=safe_name,
        format=fmt,
        text=text,
        size_bytes=size,
        sha256=digest,
        page_count=page_count,
        warnings=warnings,
    )


def extract_path(path: Path) -> ExtractedFile:
    return extract_bytes(path.name, path.read_bytes())


def discover_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise ExtractionError(f"Not a folder: {folder}")
    return sorted(
        (path for path in folder.rglob("*") if path.is_file() and not path.name.startswith(".")),
        key=lambda path: str(path.relative_to(folder)).lower(),
    )


def expand_zip(
    filename: str,
    content: bytes,
    *,
    max_files: int = 50,
    max_file_bytes: int = 20 * 1024 * 1024,
    max_total_bytes: int = 50 * 1024 * 1024,
) -> list[tuple[str, bytes]]:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise ExtractionError("Not a valid ZIP archive.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            selected = []
            total = 0
            # Check all declared sizes/counts before allocating decompressed data.
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise ExtractionError("Unsafe path in ZIP archive.")
                base = Path(name).name
                if not base or base.startswith(".") or "__MACOSX" in name.split("/"):
                    continue
                if len(selected) >= max_files:
                    raise ExtractionLimitError("ZIP expansion exceeds the batch file count limit.")
                if info.file_size > max_file_bytes:
                    raise ExtractionLimitError("ZIP member exceeds the per-file size limit.")
                total += info.file_size
                if total > max_total_bytes:
                    raise ExtractionLimitError("ZIP expansion exceeds the total batch size limit.")
                selected.append((base, info))
            return [(base, archive.read(info)) for base, info in selected]
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ExtractionError("Could not read ZIP archive.") from exc


def combine_files(files: Iterable[ExtractedFile]) -> str:
    parts: list[str] = []
    for item in sorted(files, key=lambda f: f.filename.lower()):
        body = item.text if item.text.strip() else "[no extractable text]"
        parts.append(f"---- File: {item.filename} ----\n{body}")
    return "\n\n".join(parts).strip() + "\n"
