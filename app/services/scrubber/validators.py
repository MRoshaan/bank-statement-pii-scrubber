from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    placeholder: str
    entity_type: str
    priority: int = 50


def overlap(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def is_valid_iban(value: str) -> bool:
    iban = normalize_iban(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    converted = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(converted) % 97 == 1


def luhn_valid(value: str) -> bool:
    digits = [int(ch) for ch in re.sub(r"\D", "", value)]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def valid_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    return all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)


def compact_date_ok(value: str) -> bool:
    if not value.isdigit():
        return False
    if len(value) == 8:
        year, month, day = int(value[:4]), int(value[4:6]), int(value[6:8])
        return 1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
    if len(value) == 14:
        year, month, day = int(value[:4]), int(value[4:6]), int(value[6:8])
        hour, minute, second = int(value[8:10]), int(value[10:12]), int(value[12:14])
        return (
            1990 <= year <= 2100
            and 1 <= month <= 12
            and 1 <= day <= 31
            and 0 <= hour <= 23
            and 0 <= minute <= 59
            and 0 <= second <= 59
        )
    return False


DATE_TOKEN_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b"),
    re.compile(r"\b\d{2}-[A-Za-z]{3}-\d{4}\b"),
    re.compile(r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b"),
    re.compile(r"\b\d{4}-[A-Za-z]{3}-\d{2}\b"),
    re.compile(r"\b[A-Za-z]{3}\d{2}-\d{2}:\d{2}:\d{2}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\b"),
]


def is_date_like(value: str) -> bool:
    return any(pattern.search(value) for pattern in DATE_TOKEN_PATTERNS)


def is_timestamp_like(value: str) -> bool:
    return compact_date_ok(value) and len(value) in {8, 14}


def looks_like_amount(value: str) -> bool:
    stripped = value.strip()
    if re.fullmatch(r"[-+]?\d{1,3}(?:[,.]\d{3})*(?:[.,]\d{2})", stripped):
        return True
    if re.fullmatch(r"[-+]?\d+[.,]\d{2}", stripped):
        return True
    return False


def context_window(text: str, start: int, end: int, radius: int = 60) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    if right == -1:
        right = len(text)
    return left, right
