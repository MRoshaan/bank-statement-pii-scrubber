from __future__ import annotations

from app.services.llm.context import (
    deterministic_chat_answer,
    ground_citations,
    validate_chat_payload,
    validate_payload,
)


def test_validate_payload_numeric_and_refs():
    payload = {
        "summary": "You spent 100.00 PKR.",
        "insights": [
            {
                "title": "Food",
                "detail": "Food was 100.00 PKR.",
                "evidence_refs": ["wallet.csv:1"],
                "confidence": "high",
            }
        ],
        "anomalies": [],
        "recommendations": [
            {"title": "Budget", "detail": "Review 100.00 PKR.", "evidence_refs": []}
        ],
        "data_quality_notes": [],
    }
    report = validate_payload(payload, {"wallet.csv:1"}, {100.0})
    assert report["grounded"] is True
    assert report["unsupported_numbers"] == []

    bad = {**payload, "summary": "You spent 999.00 PKR."}
    report = validate_payload(bad, {"wallet.csv:1"}, {100.0})
    assert report["grounded"] is False
    assert report["unsupported_numbers"]


def test_validate_chat_payload_filters_bad_citations():
    payload = {
        "answer": "Food was 100.00 PKR.",
        "citations": ["wallet.csv:1", "missing.csv:9"],
        "figures": [{"value": 100.0, "currency": "PKR", "label": "food"}],
        "grounded": True,
        "refusal": None,
    }
    report = validate_chat_payload(payload, {"wallet.csv:1"}, {100.0})
    assert report["grounded"] is True
    assert report["invalid_refs"] == ["missing.csv:9"]


def test_deterministic_chat_answer_food():
    facts = {
        "currencies": ["PKR"],
        "by_currency": {"PKR": {"spend": 500.0, "received": 0.0, "net": -500.0, "count": 2}},
        "by_category": {"PKR": {"Food & Dining": {"spend": 100.0, "count": 2}}},
        "largest_transactions": [
            {"ref": "wallet.csv:1", "category": "Food & Dining", "currency": "PKR"}
        ],
    }
    answer = deterministic_chat_answer("How much did I spend on food?", facts)
    assert answer is not None
    assert "100.0 PKR" in answer["answer"]
    assert answer["grounded"] is True


def test_ground_citations_prefers_matching_currency():
    class Row:
        def __init__(self, ref, category, merchant, currency):
            self.meta = {"ref": ref}
            self.category = category
            self.merchant = merchant
            self.currency = currency
            self.amount = 10
            self.balance = None
            self.txn_date = None
            self.description = ""

    rows = [
        Row("inr:1", "Cash", "ATM", "INR"),
        Row("pkr:1", "Cash", "ATM", "PKR"),
    ]
    payload = {
        "insights": [
            {
                "title": "PKR cash",
                "detail": "Cash withdrawals in PKR.",
                "evidence_refs": ["inr:1"],
                "confidence": "high",
            }
        ],
        "anomalies": [],
        "recommendations": [],
    }
    grounded = ground_citations(payload, {}, rows)
    assert grounded["insights"][0]["evidence_refs"][0] == "pkr:1"
