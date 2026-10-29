from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.scrubber.engine import scrub_text
from app.services.transactions import parse_transactions


def test_wallet_csv_parse():
    text = (
        "Customer Name,Bilal Hassan Khan,,,\n"
        "Wallet ID,bilalhk91,,,\n"
        "TIMESTAMP,TYPE,DESCRIPTION,AMOUNT,BALANCE\n"
        "2026-04-01 08:55:12,Merchant Payment,Paid to Foodpanda Karachi PK|Visa xxxx2070,-1240.50,7210.00\n"
        "2026-04-02 10:14:03,Raast In,Incoming fund transfer from Bilal Hassan Khan,25000.00,31710.00\n"
    )
    result = parse_transactions("wallet.csv", text)
    assert len(result.records) == 2
    first = result.records[0]
    assert first.txn_date == date(2026, 4, 1)
    assert first.amount == Decimal("-1240.50")
    assert first.currency == "PKR"
    assert first.merchant == "Foodpanda"
    assert first.category == "Food & Dining"


def test_indian_grouping_and_german_decimal():
    text = (
        "01-Apr-2026 | NEFT CR INFOTECH LABS PVT LTD SALARY | +₹85,000.00 | ₹1,12,340.00\n"
        "01.04.2026 | GEHALT BERLINER DATENWERK GMBH | +€3.200,00 | €4.150,20\n"
    )
    result = parse_transactions("international.docx", text)
    assert len(result.records) == 2
    assert result.records[0].amount == Decimal("85000.00")
    assert result.records[0].currency == "INR"
    assert result.records[0].txn_date == date(2026, 4, 1)
    assert result.records[1].amount == Decimal("3200.00")
    assert result.records[1].currency == "EUR"
    assert result.records[1].txn_date == date(2026, 4, 1)


def test_paypal_total_and_dates():
    text = (
        "Date, Name / Email, Type, Status, Amount, Fees, Total\n"
        "03 Apr 2026, Upwork Escrow Inc (payments@upwork.com), Payment Received, Completed, +$220.00 USD, -$4.40, +$215.60\n"
    )
    result = parse_transactions("paypal.txt", text)
    assert len(result.records) == 1
    record = result.records[0]
    assert record.txn_date == date(2026, 4, 3)
    assert record.amount == Decimal("215.60")
    assert record.currency == "USD"
    assert record.category == "Income"


def test_sample_file_categories(sample_paths):
    records = []
    for path in sample_paths:
        extracted = __import__("app.services.extractors", fromlist=["extract_path"]).extract_path(path)
        scrubbed = scrub_text(extracted.text)
        records.extend(parse_transactions(path.name, scrubbed.text).records)
    assert len(records) == 119
    currencies = {record.currency for record in records}
    assert currencies == {"PKR", "USD", "GBP", "CAD", "EUR", "INR"}
    food_pkr = sum(
        abs(record.amount)
        for record in records
        if record.category == "Food & Dining" and record.currency == "PKR"
    )
    assert food_pkr == Decimal("15219.89")
    assert any(record.merchant == "Foodpanda" for record in records)
    assert any(record.category == "Cash" for record in records)
