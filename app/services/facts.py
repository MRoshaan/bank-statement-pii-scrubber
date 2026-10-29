from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.services.transactions import TransactionRecord

EXCLUDED_MERCHANT_CATEGORIES = {
    "Transfers",
    "Income",
    "Refunds & Reversals",
    "Cash",
    "Fees & Charges",
}


def _f(value: Decimal | float | int) -> float:
    return float(round(Decimal(value), 2))


def _empty_totals() -> dict[str, float | int]:
    return {"spend": 0.0, "received": 0.0, "net": 0.0, "count": 0}


def _merchant_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def build_facts(
    records: list[TransactionRecord],
    file_summaries: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings = warnings or []
    dates = [record.txn_date for record in records if record.txn_date]
    currencies = sorted({record.currency or "UNKNOWN" for record in records})

    by_currency: dict[str, dict[str, float | int]] = {currency: _empty_totals() for currency in currencies}
    by_category: dict[str, dict[str, dict[str, float | int]]] = defaultdict(lambda: defaultdict(_empty_totals))
    monthly: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: {"spend": 0.0, "received": 0.0}))
    merchant_totals: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    counterparty_totals: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    fees = {currency: {"amount": 0.0, "count": 0} for currency in currencies}
    cash = {currency: {"amount": 0.0, "count": 0} for currency in currencies}
    transfers = {currency: {"amount": 0.0, "count": 0} for currency in currencies}

    for record in records:
        currency = record.currency or "UNKNOWN"
        amount = Decimal(record.amount)
        category = record.category
        totals = by_currency[currency]
        category_totals = by_category[currency][category]
        totals["count"] += 1
        category_totals["count"] += 1
        if amount < 0:
            spend = abs(amount)
            totals["spend"] += _f(spend)
            category_totals["spend"] += _f(spend)
            if record.txn_date:
                month = record.txn_date.strftime("%Y-%m")
                monthly[currency][month]["spend"] += _f(spend)
        elif amount > 0:
            totals["received"] += _f(amount)
            category_totals["received"] += _f(amount)
            if record.txn_date:
                month = record.txn_date.strftime("%Y-%m")
                monthly[currency][month]["received"] += _f(amount)

        if category == "Transfers":
            transfers[currency]["amount"] += _f(abs(amount))
            transfers[currency]["count"] += 1
            if record.merchant:
                cp = counterparty_totals[currency].setdefault(
                    record.merchant, {"merchant": record.merchant, "amount": 0.0, "count": 0}
                )
                cp["amount"] += _f(abs(amount))
                cp["count"] += 1
        if category == "Fees & Charges":
            fees[currency]["amount"] += _f(abs(amount))
            fees[currency]["count"] += 1
        if category == "Cash":
            cash[currency]["amount"] += _f(abs(amount))
            cash[currency]["count"] += 1
        if record.merchant and category not in EXCLUDED_MERCHANT_CATEGORIES:
            key = _merchant_key(record.merchant)
            merchant = merchant_totals[currency].setdefault(
                key, {"merchant": record.merchant, "spend": 0.0, "received": 0.0, "count": 0}
            )
            merchant["count"] += 1
            if amount < 0:
                merchant["spend"] += _f(abs(amount))
            elif amount > 0:
                merchant["received"] += _f(amount)

    for _currency, totals in by_currency.items():
        totals["spend"] = round(float(totals["spend"]), 2)
        totals["received"] = round(float(totals["received"]), 2)
        totals["net"] = round(float(totals["received"]) - float(totals["spend"]), 2)
    for _currency, categories in by_category.items():
        for category_totals in categories.values():
            category_totals["spend"] = round(float(category_totals["spend"]), 2)
            category_totals["received"] = round(float(category_totals["received"]), 2)
            category_totals["net"] = round(
                float(category_totals["received"]) - float(category_totals["spend"]), 2
            )
    for _currency, months in monthly.items():
        for month_totals in months.values():
            month_totals["spend"] = round(float(month_totals["spend"]), 2)
            month_totals["received"] = round(float(month_totals["received"]), 2)
    for _currency, values in fees.items():
        values["amount"] = round(float(values["amount"]), 2)
    for _currency, values in cash.items():
        values["amount"] = round(float(values["amount"]), 2)
    for _currency, values in transfers.items():
        values["amount"] = round(float(values["amount"]), 2)

    top_merchants_by_spend: dict[str, list[dict[str, Any]]] = {}
    top_merchants_by_count: dict[str, list[dict[str, Any]]] = {}
    for currency, merchants in merchant_totals.items():
        values = list(merchants.values())
        for item in values:
            item["spend"] = round(float(item["spend"]), 2)
            item["received"] = round(float(item["received"]), 2)
        top_merchants_by_spend[currency] = sorted(values, key=lambda item: (-item["spend"], -item["count"]))[:10]
        top_merchants_by_count[currency] = sorted(values, key=lambda item: (-item["count"], -item["spend"]))[:10]

    top_counterparties: dict[str, list[dict[str, Any]]] = {}
    for currency, counterparties in counterparty_totals.items():
        for item in counterparties.values():
            item["amount"] = round(float(item["amount"]), 2)
        top_counterparties[currency] = sorted(
            counterparties.values(), key=lambda item: (-item["amount"], -item["count"])
        )[:10]

    largest = sorted(records, key=lambda record: abs(record.amount), reverse=True)[:15]
    largest_payload = [
        {
            "ref": record.ref,
            "date": record.txn_date.isoformat() if record.txn_date else None,
            "merchant": record.merchant,
            "category": record.category,
            "amount": _f(record.amount),
            "currency": record.currency,
            "direction": record.direction,
            "description": record.description,
        }
        for record in largest
    ]

    recurring: dict[str, list[dict[str, Any]]] = {}
    for currency, merchants in merchant_totals.items():
        recurring[currency] = sorted(
            [item for item in merchants.values() if item["count"] >= 2],
            key=lambda item: (-item["count"], -item["spend"]),
        )[:10]

    duplicate_groups: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str, str], list[TransactionRecord]] = defaultdict(list)
    for record in records:
        key = (
            record.txn_date.isoformat() if record.txn_date else "",
            str(record.amount),
            record.currency,
            record.description.lower(),
        )
        groups[key].append(record)
    for (txn_date, amount, currency, description), group in groups.items():
        if len(group) > 1:
            duplicate_groups.append(
                {
                    "date": txn_date or None,
                    "amount": float(Decimal(amount)),
                    "currency": currency,
                    "description": description[:160],
                    "count": len(group),
                    "refs": [record.ref for record in group[:10]],
                }
            )
    duplicate_groups = sorted(duplicate_groups, key=lambda item: (-item["count"], item["date"] or ""))[:10]

    spend_excluding_transfers = {
        currency: round(
            float(totals["spend"])
            - float(by_category[currency].get("Transfers", {}).get("spend", 0.0))
            - float(by_category[currency].get("Refunds & Reversals", {}).get("spend", 0.0)),
            2,
        )
        for currency, totals in by_currency.items()
    }

    return {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "period": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
        },
        "transaction_count": len(records),
        "currencies": currencies,
        "by_currency": by_currency,
        "spend_excluding_transfers_and_reversals": spend_excluding_transfers,
        "by_category": {currency: dict(categories) for currency, categories in by_category.items()},
        "top_merchants_by_spend": top_merchants_by_spend,
        "top_merchants_by_count": top_merchants_by_count,
        "top_counterparties": top_counterparties,
        "largest_transactions": largest_payload,
        "recurring_merchants": recurring,
        "duplicate_groups": duplicate_groups,
        "fees": fees,
        "cash_withdrawals": cash,
        "transfers": transfers,
        "monthly": {currency: dict(months) for currency, months in monthly.items()},
        "files": file_summaries,
        "data_quality": {
            "parsed_transactions": len(records),
            "files": len(file_summaries),
            "missing_dates": sum(1 for record in records if record.txn_date is None),
            "missing_currency": sum(1 for record in records if not record.currency),
            "parse_warnings": warnings,
        },
        "notes": [
            "Amounts are signed; negative means money left the account.",
            "Currencies are not converted or summed across currencies.",
            "Transfers, income, refunds/reversals, cash, and fees are excluded from merchant rankings.",
        ],
    }
