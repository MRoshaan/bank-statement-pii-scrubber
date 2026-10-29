from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.services.scrubber.detectors import detect_all
from app.services.scrubber.mask import mask_placeholders
from app.services.scrubber.residual import scan_residual
from app.services.scrubber.spans import Span
from app.services.scrubber.validators import overlap


def resolve_spans(spans: list[Span], length: int) -> list[Span]:
    valid = [span for span in spans if 0 <= span.start < span.end <= length]
    valid.sort(key=lambda span: (-span.priority, -(span.end - span.start), span.start))
    accepted: list[Span] = []
    for span in valid:
        if any(overlap(span, existing) for existing in accepted):
            continue
        accepted.append(span)
    return sorted(accepted, key=lambda span: span.start)


@dataclass
class ScrubResult:
    text: str
    redaction_counts: dict[str, int] = field(default_factory=dict)
    findings: list[dict[str, object]] = field(default_factory=list)
    residual: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.residual


class ResidualPIIError(RuntimeError):
    def __init__(self, residual: list[dict[str, object]]):
        self.residual = residual
        types = ", ".join(sorted({str(item["entity_type"]) for item in residual}))
        super().__init__(f"Residual PII detected after scrubbing: {types}")


def scrub_text(text: str) -> ScrubResult:
    detection_text = mask_placeholders(text)
    spans = resolve_spans(detect_all(detection_text), len(text))

    pieces: list[str] = []
    cursor = 0
    counts: Counter[str] = Counter()
    placeholder_counts: Counter[tuple[str, str]] = Counter()
    for span in spans:
        pieces.append(text[cursor : span.start])
        pieces.append(span.placeholder)
        cursor = span.end
        counts[span.entity_type] += 1
        placeholder_counts[(span.entity_type, span.placeholder)] += 1
    pieces.append(text[cursor:])
    scrubbed = "".join(pieces)

    residual = scan_residual(scrubbed)
    warnings = []
    if residual:
        summary = ", ".join(
            f"{key} ({value})" for key, value in sorted(Counter(r["entity_type"] for r in residual).items())
        )
        warnings.append(f"Residual PII detector found: {summary}. The batch is blocked from LLM use.")

    findings = [
        {"entity_type": entity, "placeholder": placeholder, "count": count}
        for (entity, placeholder), count in sorted(placeholder_counts.items())
    ]
    return ScrubResult(
        text=scrubbed,
        redaction_counts=dict(sorted(counts.items())),
        findings=findings,
        residual=residual,
        warnings=warnings,
    )


def assert_clean(result: ScrubResult) -> None:
    if result.residual:
        raise ResidualPIIError(result.residual)
