from __future__ import annotations

import re

import phonenumbers

from app.services.scrubber.mask import PLACEHOLDER_SENTINEL
from app.services.scrubber.spans import Span
from app.services.scrubber.validators import (
    compact_date_ok,
    is_date_like,
    is_valid_iban,
    line_bounds,
    looks_like_amount,
    luhn_valid,
    normalize_iban,
    valid_ipv4,
)

PHONE_REGIONS = [
    "PK",
    "GB",
    "US",
    "CA",
    "DE",
    "IN",
    "AE",
    "SA",
    "AU",
    "FR",
    "NL",
    "ES",
    "IT",
    "BR",
    "ZA",
    "BD",
    "LK",
    "NG",
    "KE",
    "TR",
    "ID",
    "MY",
    "SG",
]


def _line_records(text: str):
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\n").rstrip("\r")
        yield offset, line
        offset += len(raw)


def _trim_value(value: str) -> str:
    return value.strip().rstrip(",;).")


def _add(spans: list[Span], start: int, end: int, placeholder: str, entity: str, priority: int) -> None:
    if end <= start:
        return
    spans.append(Span(start=start, end=end, placeholder=placeholder, entity_type=entity, priority=priority))


ADDRESS_RE = re.compile(
    r"(?i)(?<!\w)(?:(?:customer|billing|home|residential|registered|mailing|permanent)\s+)?"
    r"(?:address|anschrift|adresse)[ \t]*[:,-][ \t]*(?P<value>.*)$"
)


def detect_addresses(text: str) -> list[Span]:
    spans: list[Span] = []
    records = list(_line_records(text))
    for index, (offset, line) in enumerate(records):
        if re.search(r"(?i)\b(?:bank|branch)\s+address\b", line):
            continue
        match = ADDRESS_RE.search(line)
        if not match:
            continue
        value = match.group("value").strip()
        if PLACEHOLDER_SENTINEL in value:
            continue
        if value:
            start = offset + match.start("value")
            end = offset + match.end("value")
            _add(spans, start, end, "<ADDRESS>", "ADDRESS", 100)
        else:
            # A label-only address line may be followed by the address on the next
            # line. Do not swallow the next field when the value was already
            # replaced by a placeholder.
            for next_offset, next_line in records[index + 1 :]:
                stripped = next_line.strip()
                if not stripped:
                    break
                if PLACEHOLDER_SENTINEL in next_line or ":" in stripped[:50]:
                    break
                start = next_offset + len(next_line) - len(next_line.lstrip())
                _add(spans, start, next_offset + len(next_line), "<ADDRESS>", "ADDRESS", 100)
                break
    return spans


EMAIL_RE = re.compile(r"(?<![\w.])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
UPI_RE = re.compile(r"(?<![\w.])[A-Za-z0-9._%+\-]+@[A-Za-z][A-Za-z0-9.\-]{1,}")
HANDLE_RE = re.compile(r"(?<![\w.])@[A-Za-z0-9._\-]{2,}")


def detect_emails_and_handles(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in EMAIL_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<EMAIL>", "EMAIL", 90)
    for match in UPI_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<PAYMENT_HANDLE>", "PAYMENT_HANDLE", 89)
    for match in HANDLE_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<PAYMENT_HANDLE>", "PAYMENT_HANDLE", 89)
    return spans


IBAN_LABEL_RE = re.compile(
    r"\bIBAN\b[ \t]*[:#,]?[ \t]*(?P<value>[A-Za-z]{2}\d{2}[A-Za-z0-9 ]{10,40})", re.I
)
IBAN_GENERIC_RE = re.compile(r"\b[A-Za-z]{2}\d{2}(?:\s?[A-Za-z0-9]{1,4}){2,8}\b", re.I)
IBAN_LIKE_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


def _best_iban_prefix(value: str) -> str:
    value = value.strip()
    if is_valid_iban(value):
        return value
    tokens = list(re.finditer(r"[A-Za-z0-9]+", value))
    best = ""
    for count in range(1, len(tokens) + 1):
        candidate = "".join(token.group(0) for token in tokens[:count])
        if is_valid_iban(candidate):
            best = value[: tokens[count - 1].end()]
    return best or value


def detect_ibans(text: str) -> list[Span]:
    spans: list[Span] = []
    records = list(_line_records(text))
    for index, (offset, line) in enumerate(records):
        match = IBAN_LABEL_RE.search(line)
        if not match:
            continue
        value = _trim_value(match.group("value"))
        value = _best_iban_prefix(value)
        start = offset + match.start("value")
        end = start + len(value)
        normalized = normalize_iban(value)
        if not is_valid_iban(normalized) and index + 1 < len(records):
            next_offset, next_line = records[index + 1]
            continuation = next_line.strip()
            if re.fullmatch(r"\d{1,4}", continuation):
                candidate = normalize_iban(value + continuation)
                if is_valid_iban(candidate):
                    end = next_offset + next_line.find(continuation) + len(continuation)
        _add(spans, start, end, "<IBAN>", "IBAN", 98)

    for match in IBAN_GENERIC_RE.finditer(text):
        value = match.group(0)
        prefix = _best_iban_prefix(value)
        if is_valid_iban(prefix):
            _add(spans, match.start(), match.start() + len(prefix), "<IBAN>", "IBAN", 97)
    for match in IBAN_LIKE_RE.finditer(text):
        token = match.group(0)
        if is_valid_iban(token):
            continue  # already handled above
        context = text[max(0, match.start() - 220) : min(len(text), match.end() + 100)]
        if re.search(r"(?i)\b(?:iban|raast|ibft|sepa|neft|imps|transfer|bank|account)\b", context):
            _add(spans, match.start(), match.end(), "<IBAN>", "IBAN", 96)
    return spans


CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
CARD_EXPIRY_RE = re.compile(r"(?i)\b(?:expires?|expiry|valid[ \t]*(?:thru|until))\b[^\n]*?\b(0[1-9]|1[0-2])[ \t]*/[ \t]*(\d{2}|\d{4})\b")


def detect_cards(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in CARD_RE.finditer(text):
        token = match.group(0)
        digits = re.sub(r"\D", "", token)
        if not 13 <= len(digits) <= 19:
            continue
        left, right = line_bounds(text, match.start(), match.end())
        line = text[left:right]
        before = line[max(0, match.start() - left - 35) : match.start() - left]
        card_context = bool(
            re.search(r"(?i)\b(?:card|visa|mastercard|amex|discover|debit[ \t]+card|credit[ \t]+card)\b", before)
        )
        ref_context = bool(
            re.search(
                r"(?i)\b(?:ref|trace|txn|transaction|ft|ibft|neft|imps|rtgs|sepa|raast|invoice|order|"
                r"cheque|check|utr|consumer)\b",
                line,
            )
        )
        grouped = " " in token or "-" in token
        if (card_context and not ref_context) or (grouped and luhn_valid(token) and not ref_context):
            _add(spans, match.start(), match.end(), "<CARD>", "CARD", 92)
    for match in CARD_EXPIRY_RE.finditer(text):
        _add(spans, match.start(1), match.end(2), "<CARD_EXPIRY>", "CARD_EXPIRY", 89)
    return spans


ID_LABEL_RE = re.compile(
    r"\b(?:CNIC|SSN|SIN|NI(?:[ \t]*(?:Number|No))?(?![ \t]+(?:Number|No|ID)\b)|National[ \t]*Insurance(?:[ \t]*Number)?|"
    r"Aadhaar|PAN|Steuer-?ID|Tax[ \t]*ID|TIN|EIN|ITIN|Passport(?:[ \t]*(?:No|Number))?|"
    r"Driver'?s?[ \t]*License|NID|National[ \t]*ID|CPF|RG|DNI|BSN|PPS|TFN|ABN)\b"
    r"(?:[ \t]+on[ \t]+file)?(?:[ \t]+(?:No|Number|ID))?[ \t]*[:#,]?[ \t]*"
    r"(?P<value>[A-Z0-9][A-Z0-9\-\.]{3,40})",
    re.I,
)
TAX_ID_SPACED_RE = re.compile(
    r"\b(?:Steuer-?ID|Tax[ \t]*ID|TIN)\b[^\n:]{0,10}[:#,]?[ \t]*(?P<value>\d{2}\s\d{3}\s\d{3}\s\d{3})", re.I
)

NID_PATTERNS = [
    (re.compile(r"\b\d{5}-\d{7}-\d\b"), "NATIONAL_ID"),
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.I), "NATIONAL_ID"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "TAX_ID"),
]


def detect_national_ids(text: str) -> list[Span]:
    spans: list[Span] = []
    for pattern, entity in NID_PATTERNS:
        for match in pattern.finditer(text):
            _add(spans, match.start(), match.end(), f"<{entity}>", entity, 94)
    for match in ID_LABEL_RE.finditer(text):
        value = _trim_value(match.group("value"))
        if value:
            entity = "TAX_ID" if re.search(r"(?i)tax|tin|ein|itin|steuer|pan|abn", match.group(0)) else "NATIONAL_ID"
            _add(spans, match.start("value"), match.start("value") + len(value), f"<{entity}>", entity, 95)
    for match in TAX_ID_SPACED_RE.finditer(text):
        entity = "TAX_ID"
        _add(spans, match.start("value"), match.end("value"), f"<{entity}>", entity, 96)
    return spans


ROUTING_LABEL_RE = re.compile(
    r"\b(?:routing(?:[ \t]*(?:number|no))?|sort[ \t]*code|sort(?![ \t]*code)|transit(?:[ \t]*(?:number|no))?|"
    r"institution|blz|ifsc|micr|bic|swift(?:[ \t]*code)?|aba)\b[ \t]*[:#,]?[ \t]*"
    r"(?P<value>[A-Z0-9][A-Z0-9\-\/]{1,20})",
    re.I,
)
SORT_SIX_RE = re.compile(r"(?i)\bsort[ \t]*code\b[^\n]*?\b(?P<value>\d{6})\b")
BRANCH_CODE_RE = re.compile(r"(?i)\bbranch\b[^\n]*?\((?P<value>\d{2,6})\)")
IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
SORT_CODE_RE = re.compile(r"\b\d{2}-\d{2}-\d{2}\b")


def detect_routing(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in ROUTING_LABEL_RE.finditer(text):
        label = match.group(0).lower()
        value = _trim_value(match.group("value"))
        if not value:
            continue
        if not re.search(r"\d", value) and not ("bic" in label or "swift" in label):
            continue
        if "bic" in label or "swift" in label:
            placeholder, entity = "<SWIFT_BIC>", "SWIFT_BIC"
        elif "ifsc" in label:
            placeholder, entity = "<IFSC>", "IFSC"
        elif "micr" in label:
            placeholder, entity = "<MICR>", "MICR"
        else:
            placeholder, entity = "<ROUTING_NUMBER>", "ROUTING_NUMBER"
        _add(spans, match.start("value"), match.start("value") + len(value), placeholder, entity, 93)
    for match in SORT_SIX_RE.finditer(text):
        _add(spans, match.start("value"), match.end("value"), "<ROUTING_NUMBER>", "ROUTING_NUMBER", 93)
    for match in BRANCH_CODE_RE.finditer(text):
        _add(spans, match.start("value"), match.end("value"), "<BRANCH_CODE>", "BRANCH_CODE", 92)
    for match in IFSC_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<IFSC>", "IFSC", 92)
    for match in SORT_CODE_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<ROUTING_NUMBER>", "ROUTING_NUMBER", 92)
    return spans


ACCOUNT_RE = re.compile(
    r"\b(?:account(?:[ \t]*(?:number|no\.?|#))?|a/c(?:[ \t]*no\.?)?|acct|acc|konto(?:nummer)?)\b"
    r"[ \t]*[:#,]?[ \t]*(?P<value>[0-9][0-9 \t\-]{5,30}[0-9])",
    re.I,
)
MASKED_BANK_RE = re.compile(
    r"\b(?:linked\s+bank|bank|account|acct|acc|a/c)\b[^\n]*?(?P<value>(?:\*{2,}|x{2,})\d{4})\b",
    re.I,
)
GENERIC_MASKED_ACCOUNT_RE = re.compile(r"\b(?:X{4,}|\*{4,})\d{4}\b")


def detect_accounts(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in ACCOUNT_RE.finditer(text):
        value = _trim_value(match.group("value"))
        if value and re.search(r"\d{5,}", re.sub(r"\D", "", value)):
            _add(spans, match.start("value"), match.start("value") + len(value), "<ACCOUNT_NUMBER>", "ACCOUNT_NUMBER", 93)
    for match in MASKED_BANK_RE.finditer(text):
        _add(spans, match.start("value"), match.end("value"), "<ACCOUNT_NUMBER>", "ACCOUNT_NUMBER", 94)
    for match in GENERIC_MASKED_ACCOUNT_RE.finditer(text):
        left, right = line_bounds(text, match.start(), match.end())
        line = text[left:right]
        if re.search(r"(?i)\b(?:card|visa|mastercard|amex|discover|debit|credit)\b", line):
            continue
        if re.search(r"(?i)\b(?:account|acct|acc|a/c|imps|neft|transfer|self|bank)\b", line):
            _add(spans, match.start(), match.end(), "<ACCOUNT_NUMBER>", "ACCOUNT_NUMBER", 91)
    return spans


WALLET_LABEL_RE = re.compile(
    r"\b(?:wallet[ \t]*id|wallet[ \t]*account(?:[ \t]*number)?(?![ \t]+(?:Number|No|ID)\b)|upi[ \t]*id|paypal[ \t]*id|"
    r"venmo[ \t]*id|cash[ \t]*app[ \t]*id)\b[ \t]*[:#,]?[ \t]*(?P<value>[A-Za-z0-9._@\-]{3,60})",
    re.I,
)


def detect_wallet_ids(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in WALLET_LABEL_RE.finditer(text):
        value = _trim_value(match.group("value"))
        if not value:
            continue
        entity = "PAYMENT_HANDLE" if "@" in value else "WALLET_ID"
        _add(spans, match.start("value"), match.start("value") + len(value), f"<{entity}>", entity, 90)
    return spans


PHONE_LABEL_RE = re.compile(
    r"\b(?:phone|telephone|tel|mobile|cell|handy(?:nummer)?|whatsapp|contact|registered[ \t]+phone)\b"
    r"[ \t]*[:#,]?[ \t]*(?P<value>[+()0-9][0-9()\-\t /]{6,30}[0-9])",
    re.I,
)
PK_MOBILE_RE = re.compile(r"(?<!\d)(?:\+92[ \t-]?|0)3\d{2}[ \t-]?\d{7}(?!\d)")


def _plausible_phone(raw: str, text: str, start: int, end: int) -> bool:
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        return False
    if looks_like_amount(raw) or re.search(r"\d+[.,]\d{2}\b", raw):
        return False
    if is_date_like(raw):
        return False
    left, right = line_bounds(text, start, end)
    line = text[left:right].lower()
    near = text[max(0, start - 18) : start].lower()
    phone_context = bool(re.search(r"\b(?:call|phone|tel|mobile|cell|contact|whatsapp)\b", near + " " + line))
    id_context = bool(
        re.search(
            r"\b(?:amount|balance|total|credit|debit|spent|received|fee|charges|ref|trace|txn|transaction|"
            r"account|a/c|acct|iban|card|consumer|invoice|order|utr|sort|routing|transit|blz|ifsc|micr)\b",
            line,
        )
    )
    if id_context and not phone_context:
        return False
    return True


def detect_phones(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in PHONE_LABEL_RE.finditer(text):
        value = _trim_value(match.group("value"))
        if value:
            _add(spans, match.start("value"), match.start("value") + len(value), "<PHONE>", "PHONE", 94)
    for match in PK_MOBILE_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<PHONE>", "PHONE", 85)
    seen: set[tuple[int, int]] = set()
    for region in PHONE_REGIONS:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            start, end = match.start, match.end
            if (start, end) in seen:
                continue
            if not _plausible_phone(match.raw_string, text, start, end):
                continue
            seen.add((start, end))
            _add(spans, start, end, "<PHONE>", "PHONE", 72)
    return spans


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def detect_ips(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in IP_RE.finditer(text):
        if valid_ipv4(match.group(0)):
            _add(spans, match.start(), match.end(), "<IP_ADDRESS>", "IP_ADDRESS", 90)
    return spans


WALLET_MASK_RE = re.compile(
    r"\b(?:NayaPay|SadaPay|EasyPaisa|JazzCash)\s+(?P<value>(?:\*{2,}|x{2,})\d{3,4})\b", re.I
)
BANK_SUFFIX_RE = re.compile(
    r"\b(?:SadaPay|NayaPay|EasyPaisa|JazzCash|MCB|Meezan|Crescent|HBL|UBL|Bank)\s*[-]\s*(?P<value>\d{3,6})\b",
    re.I,
)


def detect_bank_suffixes(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in WALLET_MASK_RE.finditer(text):
        _add(spans, match.start("value"), match.end("value"), "<WALLET_ID>", "WALLET_ID", 93)
    for match in BANK_SUFFIX_RE.finditer(text):
        _add(spans, match.start("value"), match.end("value"), "<ACCOUNT_ID>", "ACCOUNT_ID", 90)
    return spans


REF_LABEL_RE = re.compile(
    r"\b(?:ref(?:erence)?|transaction[ \t]*id|txn(?:[ \t]*id)?|trace(?:[ \t]*(?:no|id))?|utr|"
    r"invoice(?:[ \t]*(?:no|id))?|order(?:[ \t]*(?:no|id))?|cheque(?:[ \t]*no)?|check(?:[ \t]*#)?|"
    r"mandatsref|kunden(?:nummer)?|customer[ \t]*id|statement[ \t]*request[ \t]*ref|support[ \t]*reference|"
    r"payment[ \t]*id|transfer[ \t]*id|confirmation(?:[ \t]*(?:no|id))?|authorization|auth[ \t]*code|"
    r"approval[ \t]*code|consumer(?:[ \t]*number)?|account[ \t]*reference|glaeubiger-?id|gläubiger-?id|"
    r"ft|ibft(?:[ \t]*(?:cr|dr))?|ach[ \t]*trace)\b[ \t]*[:#,]?[ \t]*"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9\-\/\.]{3,60})",
    re.I,
)
TXN_IDS_RE = re.compile(r"\btransaction[ \t]*ids?\b[ \t]*[:#]?[ \t]*(?P<value>.*)$", re.I)
MIXED_REF_RE = re.compile(r"\b[A-Z]{0,3}-?\d{4,}-?\d{4,}\b")
BANK_REF_RE = re.compile(r"\b[A-Z]{4}-[a-z0-9]{4}\b")
LONG_ALNUM_REF_RE = re.compile(r"\b[A-Z]{2,8}\d{12,}\b")


def _has_digit(value: str) -> bool:
    return any(ch.isdigit() for ch in value)


def detect_references(text: str) -> list[Span]:
    spans: list[Span] = []
    for offset, line in _line_records(text):
        txn_match = TXN_IDS_RE.search(line)
        if txn_match:
            rest_start = offset + txn_match.start("value")
            rest = txn_match.group("value")
            for token in re.finditer(r"\b[A-Z0-9][A-Z0-9\-]{5,}\b", rest, re.I):
                if _has_digit(token.group(0)):
                    _add(spans, rest_start + token.start(), rest_start + token.end(), "<REFERENCE>", "REFERENCE", 82)
        for match in REF_LABEL_RE.finditer(line):
            value = _trim_value(match.group("value"))
            if not value or not _has_digit(value):
                continue
            _add(spans, offset + match.start("value"), offset + match.start("value") + len(value), "<REFERENCE>", "REFERENCE", 84)
        for match in BANK_REF_RE.finditer(line):
            _add(spans, offset + match.start(), offset + match.end(), "<BANK_REF>", "BANK_REF", 80)
        for match in LONG_ALNUM_REF_RE.finditer(line):
            _add(spans, offset + match.start(), offset + match.end(), "<REFERENCE>", "REFERENCE", 83)
        for match in MIXED_REF_RE.finditer(line):
            value = match.group(0)
            if is_date_like(value) or compact_date_ok(re.sub(r"\D", "", value)):
                continue
            if re.search(
                r"(?i)\b(?:ref|trace|txn|transaction|ft|ibft|neft|imps|rtgs|sepa|raast|zelle|venmo|"
                r"interac|payment|transfer|invoice|order|cheque|check)\b",
                line,
            ):
                _add(spans, offset + match.start(), offset + match.end(), "<REFERENCE>", "REFERENCE", 80)
    return spans


LONG_NUMERIC_RE = re.compile(r"(?<![\w])\d{9,}(?![\w])")
REF_CONTEXT_RE = re.compile(
    r"(?i)\b(?:ref|trace|txn|transaction|id|utr|ft|ibft|neft|imps|rtgs|sepa|raast|zelle|venmo|"
    r"interac|invoice|order|cheque|check|consumer|account|acct|acc|a/c|iban|card|phone|mobile|"
    r"cell|routing|sort|transit|blz|ifsc|micr|wallet|upi|p2m|p2p|salary|credit|debit)\b"
)
AMOUNT_CONTEXT_RE = re.compile(r"(?i)\b(?:amount|balance|total|credit|debit|spent|received|fee|charges)\b")


def detect_generic_numeric_refs(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in LONG_NUMERIC_RE.finditer(text):
        token = match.group(0)
        left, right = line_bounds(text, match.start(), match.end())
        line = text[left:right]
        if compact_date_ok(token):
            prefix = text[left:match.start()]
            timestamp_field = re.fullmatch(r"(?i)\s*(?:(?:timestamp|date[ /_-]*time)\s*[:=]\s*)?", prefix)
            if not REF_CONTEXT_RE.search(line) or timestamp_field:
                continue
        before = text[max(0, match.start() - 4) : match.start()]
        after = text[match.end() : match.end() + 3]
        if AMOUNT_CONTEXT_RE.search(line) and (after.startswith(".") or re.search(r"[$€£₹]", before)):
            continue
        if REF_CONTEXT_RE.search(line) or len(token) >= 12:
            _add(spans, match.start(), match.end(), "<REFERENCE>", "REFERENCE", 78)
    return spans


BIC_PK_RE = re.compile(r"\b[A-Z]{4}PKKA\b")


def detect_bics(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in BIC_PK_RE.finditer(text):
        _add(spans, match.start(), match.end(), "<SWIFT_BIC>", "SWIFT_BIC", 93)
    return spans


def detect_all(text: str) -> list[Span]:
    spans: list[Span] = []
    spans.extend(detect_addresses(text))
    spans.extend(detect_emails_and_handles(text))
    spans.extend(detect_ibans(text))
    spans.extend(detect_cards(text))
    spans.extend(detect_national_ids(text))
    spans.extend(detect_routing(text))
    spans.extend(detect_accounts(text))
    spans.extend(detect_wallet_ids(text))
    spans.extend(detect_phones(text))
    spans.extend(detect_ips(text))
    spans.extend(detect_bank_suffixes(text))
    spans.extend(detect_references(text))
    spans.extend(detect_generic_numeric_refs(text))
    spans.extend(detect_bics(text))
    return spans
