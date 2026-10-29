from __future__ import annotations

from app.services.scrubber.detectors import detect_all
from app.services.scrubber.mask import mask_placeholders
from app.services.scrubber.validators import is_date_like, looks_like_amount

HIGH_CONFIDENCE = {
    "ADDRESS",
    "EMAIL",
    "PAYMENT_HANDLE",
    "IBAN",
    "CARD",
    "CARD_EXPIRY",
    "NATIONAL_ID",
    "TAX_ID",
    "PHONE",
    "IP_ADDRESS",
    "ROUTING_NUMBER",
    "SWIFT_BIC",
    "IFSC",
    "MICR",
    "ACCOUNT_NUMBER",
    "WALLET_ID",
    "ACCOUNT_ID",
    "BRANCH_CODE",
    "REFERENCE",
    "BANK_REF",
}


def scan_residual(text: str) -> list[dict[str, object]]:
    detection_text = mask_placeholders(text)
    hits: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()
    for span in detect_all(detection_text):
        if span.entity_type not in HIGH_CONFIDENCE:
            continue
        if span.entity_type == "REFERENCE":
            value = detection_text[span.start:span.end]
            # Short label-driven refs are too ambiguous in serialized JSON.
            # Dates and monetary values must survive the residual guard.
            if sum(char.isdigit() for char in value) < 9 or is_date_like(value) or looks_like_amount(value):
                continue
        key = (span.start, span.end, span.entity_type)
        if key in seen:
            continue
        seen.add(key)
        hits.append({"entity_type": span.entity_type, "start": span.start, "end": span.end})
    return hits
