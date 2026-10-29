from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

CURRENCY_CODES = ("PKR", "USD", "GBP", "CAD", "EUR", "INR", "AUD", "AED", "SAR")
CURRENCY_RE = re.compile(r"(?:(PKR|USD|GBP|CAD|EUR|INR|AUD|AED|SAR)|[$€£₹])\s?(\d[\d,]*(?:\.\d{1,2})?)")
DECIMAL_RE = re.compile(r"(?<![\d.])(\d[\d,]*\.\d{1,2})(?![\d.])")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
CATEGORY_HINTS = {
    "food": "Food & Dining",
    "dining": "Food & Dining",
    "restaurant": "Food & Dining",
    "eat": "Food & Dining",
    "grocery": "Groceries",
    "groceries": "Groceries",
    "supermarket": "Groceries",
    "transport": "Transport",
    "careem": "Transport",
    "uber": "Transport",
    "fuel": "Transport",
    "bill": "Bills & Utilities",
    "utility": "Bills & Utilities",
    "electric": "Bills & Utilities",
    "entertainment": "Entertainment",
    "netflix": "Entertainment",
    "spotify": "Entertainment",
    "shopping": "Shopping",
    "amazon": "Shopping",
    "daraz": "Shopping",
    "cash": "Cash",
    "fee": "Fees & Charges",
    "fees": "Fees & Charges",
    "transfer": "Transfers",
    "income": "Income",
    "salary": "Income",
    "rent": "Housing",
    "health": "Health",
}


def _round(value: Any) -> float:
    return round(float(value), 2)


def compact_facts(facts: dict[str, Any], max_merchants: int = 5, max_largest: int = 8) -> dict[str, Any]:
    keys = [
        "period",
        "transaction_count",
        "currencies",
        "by_currency",
        "spend_excluding_transfers_and_reversals",
        "by_category",
        "top_merchants_by_spend",
        "top_merchants_by_count",
        "top_counterparties",
        "recurring_merchants",
        "duplicate_groups",
        "fees",
        "cash_withdrawals",
        "transfers",
        "monthly",
        "data_quality",
        "notes",
    ]
    compact = {key: facts.get(key) for key in keys if key in facts}
    for key in ("top_merchants_by_spend", "top_merchants_by_count", "top_counterparties", "recurring_merchants"):
        if key in compact and isinstance(compact[key], dict):
            compact[key] = {
                currency: values[:max_merchants]
                for currency, values in compact[key].items()
            }
    if "largest_transactions" in facts:
        compact["largest_transactions"] = facts["largest_transactions"][:max_largest]
    if "duplicate_groups" in facts:
        compact["duplicate_groups"] = facts["duplicate_groups"][:5]
    return compact


def analysis_facts(facts: dict[str, Any], rows: Iterable[Any] = ()) -> dict[str, Any]:
    """A compact facts pack that fits Groq's free-tier TPM budget."""

    rows = list(rows)
    ref_meta = {
        (row.meta or {}).get("ref"): row
        for row in rows
        if (row.meta or {}).get("ref")
    }

    def example(
        category: str | None = None,
        merchant: str | None = None,
        currency: str | None = None,
    ) -> list[dict[str, Any]]:
        for ref, row in ref_meta.items():
            if category and row.category != category:
                continue
            if merchant and row.merchant != merchant:
                continue
            if currency and row.currency != currency:
                continue
            return [{"ref": ref}]
        return []

    filtered_categories: dict[str, dict[str, Any]] = {}
    for currency, categories in (facts.get("by_category") or {}).items():
        spending = {
            category: values
            for category, values in categories.items()
            if category not in {"Transfers", "Income", "Refunds & Reversals"}
        }
        top = sorted(spending.items(), key=lambda item: float(item[1].get("spend", 0)), reverse=True)[:3]
        filtered_categories[currency] = {
            category: {
                "spend": values.get("spend", 0),
                "count": values.get("count", 0),
                "examples": example(category=category, currency=currency),
            }
            for category, values in top
        }
    return {
        "period": facts.get("period"),
        "transaction_count": facts.get("transaction_count"),
        "currencies": facts.get("currencies"),
        "by_currency": facts.get("by_currency"),
        "spend_excluding_transfers_and_reversals": facts.get("spend_excluding_transfers_and_reversals"),
        "by_category": filtered_categories,
        "top_merchants_by_spend": {
            currency: [
                {
                    "merchant": item.get("merchant"),
                    "spend": item.get("spend"),
                    "count": item.get("count"),
                    "examples": example(merchant=item.get("merchant"), currency=currency),
                }
                for item in values[:2]
            ]
            for currency, values in (facts.get("top_merchants_by_spend") or {}).items()
        },
        "top_merchants_by_count": {
            currency: [
                {
                    "merchant": item.get("merchant"),
                    "spend": item.get("spend"),
                    "count": item.get("count"),
                    "examples": example(merchant=item.get("merchant"), currency=currency),
                }
                for item in values[:2]
            ]
            for currency, values in (facts.get("top_merchants_by_count") or {}).items()
        },
        "largest_transactions": (facts.get("largest_transactions") or [])[:3],
        "duplicate_groups": (facts.get("duplicate_groups") or [])[:1],
        "fees": facts.get("fees"),
        "cash_withdrawals": facts.get("cash_withdrawals"),
        "transfers": facts.get("transfers"),
        "data_quality": {
            key: (facts.get("data_quality") or {}).get(key)
            for key in ("parsed_transactions", "files", "missing_dates", "missing_currency")
        },
    }


def transaction_digest(rows: Iterable[Any]) -> str:
    lines: list[str] = []
    for row in rows:
        date = row.txn_date.strftime("%m-%d") if getattr(row, "txn_date", None) else "unknown"
        merchant = (row.merchant or "unknown-merchant")[:40]
        lines.append(
            f"{date} | {row.category} | {merchant} | {_round(row.amount)} {row.currency or ''}"
        )
    return "\n".join(lines)


def row_to_context(row: Any) -> dict[str, Any]:
    meta = getattr(row, "meta", None) or {}
    return {
        "ref": meta.get("ref") or f"line {getattr(row, 'source_line', '')}",
        "date": row.txn_date.isoformat() if getattr(row, "txn_date", None) else None,
        "merchant": row.merchant,
        "category": row.category,
        "amount": _round(row.amount),
        "currency": row.currency,
        "direction": row.direction,
        "description": (row.description or "")[:180],
    }


def rows_to_context(rows: Iterable[Any], limit: int = 20) -> list[dict[str, Any]]:
    return [row_to_context(row) for row in list(rows)[:limit]]


def _iter_numbers(value: Any) -> Iterable[float]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_numbers(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_numbers(item)
    elif isinstance(value, (int, float, Decimal)):
        yield _round(value)


def allowed_numbers(facts: dict[str, Any], rows: Iterable[Any] = ()) -> set[float]:
    allowed = {_round(value) for value in _iter_numbers(facts)}
    for number in range(0, 101):
        allowed.add(float(number))
    for row in rows:
        for attribute in ("amount", "balance"):
            value = getattr(row, attribute, None)
            if value is not None:
                allowed.add(_round(value))
    return allowed


def ground_citations(payload: dict[str, Any], facts: dict[str, Any], rows: Iterable[Any]) -> dict[str, Any]:
    """Replace model-chosen refs with refs that actually match the claim.

    The model is good at prose but can attach a valid-looking ref to the wrong
    transaction. This deterministic pass maps category, merchant, currency, and
    common aggregate keywords back to real rows.
    """

    rows = list(rows)
    by_category: dict[str, list[str]] = defaultdict(list)
    by_merchant: dict[str, list[str]] = defaultdict(list)
    by_currency: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        ref = (row.meta or {}).get("ref")
        if not ref:
            continue
        by_category[row.category].append(ref)
        if row.merchant:
            by_merchant[row.merchant.casefold()].append(ref)
        if row.currency:
            by_currency[row.currency].append(ref)

    categories = set(by_category)
    merchants = sorted(by_merchant)
    currencies = set(by_currency)
    keyword_categories = {
        "cash": "Cash",
        "fee": "Fees & Charges",
        "fees": "Fees & Charges",
        "transfer": "Transfers",
        "income": "Income",
        "salary": "Income",
        "refund": "Refunds & Reversals",
        "reversal": "Refunds & Reversals",
        "duplicate": None,
    }

    for key in ("insights", "anomalies", "recommendations"):
        for item in payload.get(key, []) or []:
            text = f"{item.get('title', '')} {item.get('detail', '')}".casefold()
            mentioned_categories = {category for category in categories if category.casefold() in text}
            mentioned_merchants = {merchant for merchant in merchants if len(merchant) >= 4 and merchant in text}
            mentioned_currencies = {currency for currency in currencies if currency.casefold() in text}
            for keyword, category in keyword_categories.items():
                if keyword in text and category:
                    mentioned_categories.add(category)
            scored: list[tuple[int, str]] = []
            for row in rows:
                ref = (row.meta or {}).get("ref")
                if not ref:
                    continue
                score = 0
                if row.category in mentioned_categories:
                    score += 4
                if row.merchant and row.merchant.casefold() in mentioned_merchants:
                    score += 4
                if row.currency and row.currency in mentioned_currencies:
                    score += 2
                if score:
                    scored.append((score, ref))
            scored.sort(key=lambda item: -item[0])
            refs = list(dict.fromkeys(ref for _, ref in scored))[:3]
            if refs:
                item["evidence_refs"] = refs
    return payload


def _parse_claim_number(raw: str) -> float | None:
    cleaned = raw.replace(",", "")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def extract_number_claims(text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for match in CURRENCY_RE.finditer(text):
        value = _parse_claim_number(match.group(2))
        if value is not None:
            claims.append({"raw": match.group(0), "value": value, "kind": "currency"})
    for match in DECIMAL_RE.finditer(text):
        value = _parse_claim_number(match.group(1))
        if value is not None:
            claims.append({"raw": match.group(0), "value": value, "kind": "decimal"})
    for match in PERCENT_RE.finditer(text):
        value = _parse_claim_number(match.group(1))
        if value is not None:
            claims.append({"raw": match.group(0), "value": value, "kind": "percent"})
    deduped: dict[tuple[float, str], dict[str, Any]] = {}
    for claim in claims:
        deduped[(claim["value"], claim["kind"])] = claim
    return list(deduped.values())


def validate_payload(
    payload: dict[str, Any],
    valid_refs: set[str],
    allowed: set[float],
) -> dict[str, Any]:
    text_parts: list[str] = [str(payload.get("summary", ""))]
    refs: list[str] = []
    for key in ("insights", "anomalies", "recommendations"):
        for item in payload.get(key, []) or []:
            text_parts.append(str(item.get("title", "")))
            text_parts.append(str(item.get("detail", "")))
            refs.extend(str(ref) for ref in item.get("evidence_refs", []) or [])
    text_parts.extend(str(note) for note in payload.get("data_quality_notes", []) or [])
    invalid_refs = sorted({ref for ref in refs if ref and ref not in valid_refs})
    claims = extract_number_claims(" ".join(text_parts))
    unsupported = [
        claim for claim in claims if round(float(claim["value"]), 2) not in allowed
    ]
    return {
        "grounded": not invalid_refs and not unsupported,
        "checked_refs": sorted(set(refs)),
        "invalid_refs": invalid_refs,
        "checked_numbers": claims,
        "unsupported_numbers": unsupported,
        "checked_at": None,
    }


def validate_chat_payload(
    payload: dict[str, Any],
    valid_refs: set[str],
    allowed: set[float],
) -> dict[str, Any]:
    answer = str(payload.get("answer", ""))
    citations = [str(ref) for ref in payload.get("citations", []) or []]
    figures = payload.get("figures", []) or []
    text = answer + " " + " ".join(str(figure.get("label", "")) for figure in figures if isinstance(figure, dict))
    claims = extract_number_claims(text)
    unsupported = [
        claim for claim in claims if round(float(claim["value"]), 2) not in allowed
    ]
    invalid_refs = sorted({ref for ref in citations if ref and ref not in valid_refs})
    invalid_figures = []
    for figure in figures:
        if not isinstance(figure, dict):
            invalid_figures.append(figure)
            continue
        value = figure.get("value")
        try:
            if round(float(value), 2) not in allowed:
                invalid_figures.append(figure)
        except (TypeError, ValueError):
            invalid_figures.append(figure)
    return {
        # A wrong optional citation is filtered; an unsupported number is a
        # grounding failure and forces the deterministic fallback.
        "grounded": not unsupported and not invalid_figures,
        "checked_refs": citations,
        "invalid_refs": invalid_refs,
        "checked_numbers": claims,
        "unsupported_numbers": unsupported,
        "invalid_figures": invalid_figures,
    }


def deterministic_analysis(facts: dict[str, Any]) -> dict[str, Any]:
    by_currency = facts.get("by_currency", {})
    currencies = facts.get("currencies", [])
    period = facts.get("period", {})
    summary = (
        f"Analyzed {facts.get('transaction_count', 0)} transactions across "
        f"{len(currencies)} currencies for {period.get('start')} to {period.get('end')}. "
        "Totals are reported per currency; no FX conversion is applied."
    )
    insights: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    for currency in currencies:
        totals = by_currency.get(currency, {})
        categories = {
            category: values
            for category, values in facts.get("by_category", {}).get(currency, {}).items()
            if category not in {"Transfers", "Income", "Refunds & Reversals"}
        }
        if categories:
            top_category, top_values = max(
                categories.items(), key=lambda item: float(item[1].get("spend", 0.0))
            )
            insights.append(
                {
                    "title": f"Largest spending category in {currency}",
                    "detail": (
                        f"{top_category} accounts for {top_values.get('spend', 0)} {currency} "
                        f"across {top_values.get('count', 0)} transactions."
                    ),
                    "evidence_refs": [],
                    "confidence": "high",
                }
            )
        top_merchants = facts.get("top_merchants_by_spend", {}).get(currency, [])
        if top_merchants:
            merchant = top_merchants[0]
            insights.append(
                {
                    "title": f"Top merchant by spend in {currency}",
                    "detail": (
                        f"{merchant.get('merchant')} is the highest-spend merchant at "
                        f"{merchant.get('spend', 0)} {currency} across {merchant.get('count', 0)} transactions."
                    ),
                    "evidence_refs": [],
                    "confidence": "high",
                }
            )
        recommendations.append(
            {
                "title": f"Review {currency} budget",
                "detail": (
                    f"Net movement in {currency} is {totals.get('net', 0)}. "
                    "Set category budgets from the largest categories and revisit transfers separately."
                ),
                "evidence_refs": [],
            }
        )
    duplicates = facts.get("duplicate_groups", [])
    if duplicates:
        group = duplicates[0]
        anomalies.append(
            {
                "title": "Possible duplicate transactions",
                "detail": (
                    f"{group.get('count')} transactions share the same date, amount and description "
                    f"({group.get('amount')}). Confirm whether they are genuine duplicates."
                ),
                "evidence_refs": group.get("refs", []),
                "severity": "medium",
            }
        )
    fees = facts.get("fees", {})
    if any(float(value.get("amount", 0)) > 0 for value in fees.values()):
        anomalies.append(
            {
                "title": "Bank fees and charges",
                "detail": "Fees and charges appear in the statement; review them separately from merchant spending.",
                "evidence_refs": [],
                "severity": "low",
            }
        )
    return {
        "summary": summary,
        "insights": insights[:8],
        "anomalies": anomalies[:5],
        "recommendations": recommendations[:6],
        "data_quality_notes": [
            f"Parsed {facts.get('data_quality', {}).get('parsed_transactions', 0)} transactions; "
            f"{facts.get('data_quality', {}).get('missing_dates', 0)} missing dates, "
            f"{facts.get('data_quality', {}).get('missing_currency', 0)} missing currencies."
        ],
    }


def deterministic_chat_answer(question: str, facts: dict[str, Any]) -> dict[str, Any] | None:
    query = question.lower()
    by_currency = facts.get("by_currency", {})
    currencies = facts.get("currencies", [])
    category = next((value for key, value in CATEGORY_HINTS.items() if key in query), None)

    if category:
        parts: list[str] = []
        citations: list[str] = []
        for currency in currencies:
            values = facts.get("by_category", {}).get(currency, {}).get(category)
            if values:
                parts.append(
                    f"{values.get('spend', 0)} {currency} across {values.get('count', 0)} transactions"
                )
                for item in facts.get("largest_transactions", []):
                    if item.get("category") == category and item.get("currency") == currency:
                        citations.append(item.get("ref"))
                        if len(citations) >= 3:
                            break
        if parts:
            return {
                "answer": f"{category} spending: " + "; ".join(parts) + ".",
                "citations": [ref for ref in citations if ref],
                "grounded": True,
                "source": "deterministic",
            }

    if "most often" in query or ("merchant" in query and "often" in query):
        parts = []
        citations = []
        for currency in currencies:
            values = facts.get("top_merchants_by_count", {}).get(currency, [])
            if values:
                top = values[0]
                parts.append(f"{top.get('merchant')} ({top.get('count')} transactions, {top.get('spend')} {currency})")
                for item in facts.get("largest_transactions", []):
                    if item.get("merchant") == top.get("merchant") and item.get("currency") == currency:
                        citations.append(item.get("ref"))
        if parts:
            return {
                "answer": "Most frequent merchants: " + "; ".join(parts) + ".",
                "citations": [ref for ref in citations if ref][:5],
                "grounded": True,
                "source": "deterministic",
            }

    if "top merchant" in query or ("merchant" in query and ("most" in query or "highest" in query)):
        parts = []
        for currency in currencies:
            values = facts.get("top_merchants_by_spend", {}).get(currency, [])
            if values:
                top = values[0]
                parts.append(f"{top.get('merchant')} ({top.get('spend')} {currency}, {top.get('count')} transactions)")
        if parts:
            return {
                "answer": "Top merchants by spend: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }

    if "fee" in query or "charge" in query:
        parts = [f"{value.get('amount', 0)} {currency}" for currency, value in facts.get("fees", {}).items() if value.get("count")]
        if parts:
            return {
                "answer": "Fees and charges: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }

    if "cash" in query:
        parts = [f"{value.get('amount', 0)} {currency}" for currency, value in facts.get("cash_withdrawals", {}).items() if value.get("count")]
        if parts:
            return {
                "answer": "Cash withdrawals: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }

    if "transfer" in query:
        parts = [f"{value.get('amount', 0)} {currency}" for currency, value in facts.get("transfers", {}).items() if value.get("count")]
        if parts:
            return {
                "answer": "Transfers: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }

    if "income" in query or "received" in query or "salary" in query:
        parts = [f"{value.get('received', 0)} {currency}" for currency, value in by_currency.items()]
        if parts:
            return {
                "answer": "Money received: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }

    if "spend" in query or "spent" in query or "total" in query:
        parts = [
            f"{facts.get('spend_excluding_transfers_and_reversals', {}).get(currency, 0)} {currency}"
            for currency in currencies
        ]
        if parts:
            return {
                "answer": "Spending excluding transfers and reversals: " + "; ".join(parts) + ".",
                "citations": [],
                "grounded": True,
                "source": "deterministic",
            }
    return None


def markdown_from_result(result: dict[str, Any]) -> str:
    facts = result.get("facts", {})
    lines: list[str] = ["# Budget analysis", ""]
    lines.append(result.get("summary", ""))
    lines.append("")
    lines.append("## Spending by currency")
    lines.append("")
    lines.append("| Currency | Spend | Received | Net | Transactions |")
    lines.append("|---|---:|---:|---:|---:|")
    for currency, values in facts.get("by_currency", {}).items():
        lines.append(
            f"| {currency} | {values.get('spend', 0)} | {values.get('received', 0)} | "
            f"{values.get('net', 0)} | {values.get('count', 0)} |"
        )
    lines.append("")
    lines.append("## Insights")
    for item in result.get("insights", []):
        lines.append(f"- **{item.get('title', 'Insight')}** — {item.get('detail', '')}")
    lines.append("")
    lines.append("## Anomalies")
    for item in result.get("anomalies", []):
        lines.append(f"- **{item.get('title', 'Anomaly')}** — {item.get('detail', '')}")
    lines.append("")
    lines.append("## Recommendations")
    for item in result.get("recommendations", []):
        lines.append(f"- **{item.get('title', 'Recommendation')}** — {item.get('detail', '')}")
    lines.append("")
    validation = result.get("validation", {})
    lines.append(
        f"_Grounding: {'validated' if validation.get('grounded') else 'needs review'}; "
        f"{len(validation.get('unsupported_numbers', []))} unsupported number(s), "
        f"{len(validation.get('invalid_refs', []))} invalid citation(s)._"
    )
    return "\n".join(lines).strip() + "\n"
