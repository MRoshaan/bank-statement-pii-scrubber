from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MONTHS = {name.lower(): index for index, name in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
)}

DATE_PREFIX_RE = re.compile(
    r"^\s*(?P<date>"
    r"\d{1,2}\s+[A-Za-z]{3}\s+\d{4}|"
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|"
    r"\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}-[A-Za-z]{3}-\d{4}|"
    r"\d{4}-[A-Za-z]{3}-\d{2}"
    r")\b"
)
TIME_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}\b")
AMOUNT_RE = re.compile(
    r"(?<![\w])(?P<sign>[+-]?)\s*"
    r"(?P<currency>C\$|A\$|[$€£₹]|PKR|USD|GBP|CAD|EUR|INR|AUD|AED|SAR)?\s?"
    r"(?P<number>\d{1,3}(?:,\d{2,3})+\.\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:[ \u00a0]\d{3})+[.,]\d{2}|\d+[.,]\d{2})"
    r"(?:\s?(?P<dc>Cr|Dr|CR|DR))?(?![\w])"
)
REFERENCE_HINTS = re.compile(
    r"(?i)\b(?:ref|trace|txn|transaction|id|utr|ft|ibft|neft|imps|rtgs|sepa|raast|zelle|venmo|"
    r"interac|invoice|order|cheque|check|consumer|account|acct|acc|a/c|iban|card|phone|mobile|"
    r"cell|routing|sort|transit|blz|ifsc|micr|wallet|upi|p2m|p2p|salary|credit|debit)\b"
)
SKIP_CONTINUATION = re.compile(
    r"(?i)^(?:transaction\s*ids?|customer\s*support|generated|date,|bank\b|statement\b|account\b|"
    r"customer\b|address\b|iban\b|bic\b|branch\b|sort\s*code|routing|transit|institution|"
    r"opening\s*balance|closing\s*balance|total\s*(?:spent|received)|wallet\s*id|"
    r"registered|linked|statement\s*period|timestamp,)"
)


@dataclass
class TransactionRecord:
    filename: str
    line_no: int
    txn_date: date | None
    txn_time: str | None
    description: str
    merchant: str | None
    category: str
    amount: Decimal
    currency: str
    direction: str
    balance: Decimal | None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.filename}:{self.line_no}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "filename": self.filename,
            "line_no": self.line_no,
            "date": self.txn_date.isoformat() if self.txn_date else None,
            "time": self.txn_time,
            "description": self.description,
            "merchant": self.merchant,
            "category": self.category,
            "amount": float(self.amount),
            "currency": self.currency,
            "direction": self.direction,
            "balance": float(self.balance) if self.balance is not None else None,
            "meta": self.meta,
        }


@dataclass
class ParseResult:
    records: list[TransactionRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _month_number(token: str) -> int | None:
    return MONTHS.get(token[:3].lower())


def parse_date_token(token: str, context: str = "") -> date | None:
    token = token.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%Y-%b-%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", token)
    if match:
        month = _month_number(match.group(2))
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
    match = re.fullmatch(r"(\d{1,2})([-/.])(\d{1,2})\2(\d{4})", token)
    if match:
        first, _sep, second, year = (
            int(match.group(1)),
            match.group(2),
            int(match.group(3)),
            int(match.group(4)),
        )
        us_context = bool(re.search(r"(?i)\b(?:USA|United States|US)\b", context)) or (
            "$" in context and "£" not in context and "₹" not in context
        )
        month, day = (first, second) if us_context else (second, first)
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _currency_for(token: str, context: str) -> str:
    upper = token.upper()
    for code in ("PKR", "USD", "GBP", "CAD", "EUR", "INR", "AUD", "AED", "SAR"):
        if code in upper:
            return code
    if "C$" in upper:
        return "CAD"
    if "A$" in upper:
        return "AUD"
    if "£" in token:
        return "GBP"
    if "€" in token:
        return "EUR"
    if "₹" in token:
        return "INR"
    if "$" in token:
        if re.search(r"(?i)\bCanada\b", context):
            return "CAD"
        if re.search(r"(?i)\bAustralia\b", context):
            return "AUD"
        return "USD"
    for code in ("PKR", "USD", "GBP", "CAD", "EUR", "INR", "AUD", "AED", "SAR"):
        if code in context.upper():
            return code
    if re.search(
        r"(?i)\b(?:Pakistan|CNIC|Raast|NayaPay|SadaPay|EasyPaisa|JazzCash|Foodpanda)\b|PK\d{2}[A-Z0-9]",
        context,
    ):
        return "PKR"
    if re.search(r"(?i)\bIndia\b|₹", context):
        return "INR"
    if re.search(r"(?i)\bCanada\b|C\$", context):
        return "CAD"
    if re.search(r"(?i)\b(?:United Kingdom|UK)\b|£", context):
        return "GBP"
    if re.search(r"(?i)\bGermany\b|€", context):
        return "EUR"
    if re.search(r"(?i)\b(?:USA|United States)\b|\$", context):
        return "USD"
    return ""


def _parse_number(raw: str) -> Decimal | None:
    value = raw.strip().replace(" ", "")
    value = value.replace("Cr", "").replace("Dr", "").replace("CR", "").replace("DR", "")
    value = re.sub(r"[^\d,.\-+]", "", value)
    if not value:
        return None
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        if len(parts) > 2:
            value = value.replace(",", "")
        elif len(parts) == 2 and len(parts[-1]) == 2:
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _candidate_amounts(body: str, context: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for match in AMOUNT_RE.finditer(body):
        number = match.group("number")
        currency = match.group("currency") or ""
        dc = match.group("dc") or ""
        sign = match.group("sign") or ""
        has_decimal = bool(re.search(r"[.,]\d{2}$", number))
        if not (has_decimal or currency or dc or sign):
            continue
        value = _parse_number(number)
        if value is None:
            continue
        if dc.lower() == "dr":
            value = -abs(value)
        elif dc.lower() == "cr":
            value = abs(value)
        elif sign == "-":
            value = -abs(value)
        elif sign == "+":
            value = abs(value)
        candidates.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(0),
                "value": value,
                "currency": _currency_for(match.group(0), context),
                "dc": dc,
                "sign": sign,
            }
        )
    return candidates


def _clean_description(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip(" |,-")
    value = re.sub(r"<[A-Z][A-Z0-9_*]*>", "", value)
    value = re.sub(r"(?i)\b(?:card|visa|mastercard|amex|discover)[ \t]+(?:x{2,}|\*{2,}|ending[ \t]+)?\d{3,4}\b", "", value)
    value = re.sub(r"(?i)\b(?:consumer[ \t]*number|nickname|alias)\s*:?", "", value)
    value = re.sub(r"\s+", " ", value).strip(" |,-:")
    return value[:500]


def _merchant_from_description(description: str, txn_type: str = "") -> str:
    value = re.sub(r"<[A-Z][A-Z0-9_*]*>", "", description)
    if "|" in value:
        first, rest = value.split("|", 1)
        if re.match(r"(?i)^mobile top-?up", first.strip()):
            value = rest if rest.strip() else first
        else:
            value = first
    value = re.sub(r"^[\s|,-]+", "", value)
    patterns = [
        r"(?i)^faster payment to\s+",
        r"(?i)^salary(?: credit)?\s+",
        r"(?i)^payroll deposit\s+",
        r"(?i)^paid to\s+",
        r"(?i)^pos purchase\s+",
        r"(?i)^pos\s+",
        r"(?i)^online\s+",
        r"(?i)^merchant payment\s+",
        r"(?i)^payment to\s+",
        r"(?i)^money sent to\s+",
        r"(?i)^money received from\s+",
        r"(?i)^incoming fund transfer from\s+",
        r"(?i)^outgoing fund transfer to\s+",
        r"(?i)^transfer to\s+",
        r"(?i)^transfer from\s+",
        r"(?i)^salary credit\s+",
        r"(?i)^payroll deposit\s+",
        r"(?i)^gehalt\s+",
        r"(?i)^neft cr\s+",
        r"(?i)^direct debit\s+",
        r"(?i)^sepa-?ueberweisung an\s+",
        r"(?i)^sepa-?überweisung an\s+",
        r"(?i)^billpay\s+",
        r"(?i)^bill payment\s+",
        r"(?i)^utility bill\s+",
        r"(?i)^cheque(?:[ \t]*no)?\s+",
        r"(?i)^clearing favouring\s+",
        r"(?i)^upi/[^/]+/[^/]+/",
        r"(?i)^imps/[^/]+/[^/]+/to\s+",
        r"(?i)^refund from\s+",
        r"(?i)^cash withdrawn at\s+",
        r"(?i)^cash withdrawal\s+",
        r"(?i)^atm wdl\s+",
        r"(?i)^fee\s+",
        r"(?i)^charges\s+",
    ]
    for pattern in patterns:
        value = re.sub(pattern, "", value, count=1)
    if re.match(r"(?i)^(?:upi|imps|neft|rtgs)/", value):
        parts = [part.strip() for part in value.split("/") if part.strip()]
        preferred = [part for part in parts if re.match(r"(?i)^(?:to\s+)?[A-Z][A-Z .'-]{3,}$", part)]
        if preferred:
            value = re.sub(r"(?i)^to\s+", "", preferred[-1])
    elif re.match(r"(?i)^(?:raast|ibft|ft)\b", value):
        match = re.search(r"(?i)\b(?:others|to|from)\s+([A-Z][A-Z .'-]{3,})", value)
        if match:
            value = match.group(1)
        else:
            value = "RAAST Transfer"
    else:
        value = re.sub(r"(?i)\b(?:visa|mastercard|amex|discover|debit|credit|card)\b.*$", "", value)
        value = re.sub(r"(?i)\b(?:transaction id|trace|ref|order|invoice|consumer number|nickname|alias)\b.*$", "", value)
        value = re.sub(r"(?i)\biban\b.*$", "", value)
        value = re.sub(r"(?i)\b(?:verwendung|miete|april)\b.*$", "", value)
        value = re.sub(r"(?i)\b(?:sort|acc|account)\b.*$", "", value)
        value = re.sub(r"(?i),\s*(?:crescent|mcb|meezan|hbl|ubl|bank)\b.*$", "", value)
        value = re.sub(r"(?i)\b(?:dividend warrant|withdrawal ref)\b.*$", "", value)
        value = re.sub(r"(?i)\b(?:karachi|lahore|islamabad|rawalpindi|pune|toronto|berlin|manchester|austin|amsterdam|stockholm)\b.*$", "", value)
    value = re.sub(r"\(\)", "", value)
    value = re.sub(r"(?i)\b(?:my|office)\s+(?:ufone|sim)\b", "", value)
    value = re.sub(r"(?i)\bconsumer name\b.*$", "", value)
    value = value.split(",", 1)[0]
    value = re.sub(r"(?i)^cheque\s+no\s*$", "Cheque", value)
    value = re.sub(r"(?i)\b(?:pvt ltd|private limited|llc|inc|ltd|limited|corp|corporation|gmbh|plc)\b", lambda m: m.group(0), value)
    value = re.sub(r"\s+", " ", value).strip(" |,-:.")
    if re.search(r"(?i)\b(?:monthly service charges|sms banking charges|transfer fee|wht|service charge)\b", value):
        return "Bank Fee"
    if not value:
        value = txn_type or description[:80]
    return value[:120].strip()


CATEGORY_RULES: list[tuple[str, str]] = [
    ("Refunds & Reversals", r"\brefund|\breversal|\bdispute\b|\bchargeback\b"),
    ("Income", r"\bsalary\b|\bpayroll\b|\bgehalt\b|\bincome\b|\binterest\b|\bdividend\b|\bfreelance\b|\bupwork\b|\bfiverr\b|\bgulf freelance\b|\bneft cr\b|\bprofit payment\b|\bcredit interest\b"),  # noqa: E501
    ("Cash", r"\batm\b|\bcash withdraw|\bcash withdr"),
    ("Food & Dining", r"foodpanda|\bkfc\b|starbucks|tim hortons|restaurant|\bcafe\b|\bchai\b|zomato|swiggy|\bfood\b|pizza|burger|biryani|bakery"),
    ("Groceries", r"supermarket|super market|groceries|whole foods|\btesco\b|\brewe\b|loblaws|imtiaz|\bgeneral store\b|\bmarket\b"),
    ("Transport", r"careem|\buber\b|presto|\bbvg\b|\btransport\b|\bfuel\b|petrol|\bshell\b|total energies|\bmetro\b|\bbus\b|\btrain\b|parking"),
    ("Bills & Utilities", r"\bbill\b|\butility\b|electric|\bwater\b|\benergy\b|council tax|internet|stormfiber|vodafone|\bufone\b|\bzong\b|\bjazz\b|\bmobile\b|top-?up|\bphone\b"),
    ("Entertainment", r"netflix|spotify|\bsteam\b|entertainment|cinema|\bgame\b|\bplaystation\b|xbox"),
    ("Shopping", r"amazon|daraz|shopping|chase up|mktplace|marketplace|store"),
    ("Health", r"pharmacy|hospital|clinic|health|doctor"),
    ("Education", r"school|university|education|course|udemy|coursera"),
    ("Software & Subscriptions", r"github|namecheap|domain|software|subscription"),
    ("Housing", r"\brent\b|\bmiete\b|\bmortgage\b|\bhousing\b"),
    ("Fees & Charges", r"\bfee\b|\bfees\b|\bcharges?\b|\bwht\b|\btax\b|\bcommission\b"),
    ("Transfers", r"transfer|raast|zelle|venmo|interac|remitly|payoneer|sadapay|nayapay|easypaisa|money sent|money received|cricket fund|ammi|self|ueberweisung|überweisung|sepa"),
]


def categorize(description: str, merchant: str, txn_type: str = "") -> str:
    text = f"{description} {merchant} {txn_type}".lower()
    for category, pattern in CATEGORY_RULES:
        if re.search(pattern, text, re.I):
            return category
    return "Other"


def _record_from_parts(
    filename: str,
    line_no: int,
    raw_date: str | None,
    body: str,
    context: str,
    txn_type: str = "",
    explicit_amount: str | None = None,
    explicit_balance: str | None = None,
    explicit_currency: str = "",
    meta: dict[str, Any] | None = None,
) -> TransactionRecord | None:
    txn_date = parse_date_token(raw_date, body) if raw_date else None
    time_match = TIME_RE.search(body)
    txn_time = time_match.group(0) if time_match else None
    if explicit_amount is not None:
        amount = _parse_number(explicit_amount)
        if amount is None:
            return None
        if explicit_amount.strip().startswith("-"):
            amount = -abs(amount)
        elif explicit_amount.strip().startswith("+"):
            amount = abs(amount)
        balance = _parse_number(explicit_balance) if explicit_balance else None
        description = _clean_description(body)
        currency = explicit_currency or _currency_for(explicit_amount, context)
    else:
        candidates = _candidate_amounts(body, context)
        if len(candidates) < 2:
            return None
        amount_candidate, balance_candidate = candidates[-2], candidates[-1]
        amount = amount_candidate["value"]
        balance = balance_candidate["value"]
        description = _clean_description(body[: amount_candidate["start"]])
        currency = amount_candidate["currency"] or _currency_for(body, context)
        if not description:
            description = _clean_description(body)
        if len(candidates) > 2 and not currency:
            currency = _currency_for(body, context)
    if amount == 0 and not description:
        return None
    if amount > 0:
        direction = "credit"
    elif amount < 0:
        direction = "debit"
    else:
        direction = "neutral"
    merchant = _merchant_from_description(description, txn_type)
    category = categorize(description, merchant, txn_type)
    return TransactionRecord(
        filename=filename,
        line_no=line_no,
        txn_date=txn_date,
        txn_time=txn_time,
        description=description,
        merchant=merchant,
        category=category,
        amount=amount,
        currency=currency,
        direction=direction,
        balance=balance,
        meta={**(meta or {}), "type": txn_type},
    )


def _parse_wallet_csv(filename: str, text: str, warnings: list[str]) -> list[TransactionRecord]:
    rows = list(csv.reader(io.StringIO(text)))
    header_index = None
    for index, row in enumerate(rows):
        if row and "TIMESTAMP" in row[0].upper() and "AMOUNT" in " ".join(row).upper():
            header_index = index
            break
    if header_index is None:
        return []
    records: list[TransactionRecord] = []
    for line_no, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if len(row) < 5 or not row[0].strip():
            continue
        timestamp, txn_type, description, amount_text, balance_text = row[:5]
        raw_date = timestamp.split(" ")[0]
        record = _record_from_parts(
            filename,
            line_no,
            raw_date,
            description,
            text,
            txn_type=txn_type,
            explicit_amount=amount_text,
            explicit_balance=balance_text,
            meta={"timestamp": timestamp},
        )
        if record:
            time_match = TIME_RE.search(timestamp)
            record.txn_time = time_match.group(0) if time_match else None
            record.description = _clean_description(description)
            record.meta["timestamp"] = timestamp
            records.append(record)
    return records


def _parse_paypal(filename: str, text: str, warnings: list[str]) -> list[TransactionRecord]:
    rows = list(csv.reader(io.StringIO(text)))
    header_index = None
    for index, row in enumerate(rows):
        joined = " ".join(row).lower()
        if "date" in joined and "amount" in joined and "total" in joined:
            header_index = index
            break
    if header_index is None:
        return []
    records: list[TransactionRecord] = []
    for line_no, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if len(row) < 7 or not row[0].strip():
            continue
        raw_date, name, txn_type, status, amount_text, fees_text, total_text = row[:7]
        if not re.search(r"\d", total_text):
            continue
        record = _record_from_parts(
            filename,
            line_no,
            raw_date,
            name,
            text,
            txn_type=txn_type,
            explicit_amount=total_text,
            explicit_balance=None,
            meta={"status": status, "fees": fees_text, "gross_amount": amount_text, "name": name},
        )
        if record:
            record.description = _clean_description(f"{name} — {txn_type} ({status})")
            record.meta.update({"fees": fees_text, "gross_amount": amount_text, "name": name})
            record.merchant = _merchant_from_description(name, txn_type)
            record.category = categorize(record.description, record.merchant or "", txn_type)
            records.append(record)
    return records


def _parse_lines(filename: str, text: str, warnings: list[str]) -> list[TransactionRecord]:
    records: list[TransactionRecord] = []
    current: TransactionRecord | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        date_match = DATE_PREFIX_RE.match(line)
        if date_match:
            raw_date = date_match.group("date")
            body = line[date_match.end() :].strip()
            record = _record_from_parts(filename, line_no, raw_date, body, text)
            if record:
                records.append(record)
                current = record
            else:
                current = None
            continue
        stripped = line.strip()
        if not stripped or SKIP_CONTINUATION.match(stripped):
            current = None
            continue
        if current is not None and len(current.description) < 600:
            current.description = _clean_description(f"{current.description} {stripped}")
            current.merchant = _merchant_from_description(current.description, current.meta.get("type", ""))
            current.category = categorize(current.description, current.merchant or "", current.meta.get("type", ""))
    return records


def parse_transactions(filename: str, text: str) -> ParseResult:
    warnings: list[str] = []
    if "TIMESTAMP,TYPE,DESCRIPTION,AMOUNT,BALANCE" in text.upper():
        records = _parse_wallet_csv(filename, text, warnings)
    elif re.search(r"(?i)Date,\s*Name / Email,\s*Type,\s*Status,\s*Amount", text):
        records = _parse_paypal(filename, text, warnings)
    else:
        records = _parse_lines(filename, text, warnings)
    if not records and text.strip():
        warnings.append("No transactions could be parsed from this file.")
    return ParseResult(records=records, warnings=warnings)
