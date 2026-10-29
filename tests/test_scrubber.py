from __future__ import annotations

import pytest

from app.services.extractors import combine_files, extract_path
from app.services.scrubber.engine import ResidualPIIError, assert_clean, scrub_text
from app.services.scrubber.residual import scan_residual

KNOWN_PII = [
    "bilal.hkhan91@gmail.com",
    "hamza.qureshi.dev@gmail.com",
    "payments@upwork.com",
    "d.whitfield@outlook.com",
    "marcus.alvarez88@yahoo.com",
    "priya.raghu@proton.me",
    "lukas.brandt@web.de",
    "rahul.desh@gmail.com",
    "rohan.raghu@gmail.com",
    "ayesha.sid@nayapay",
    "hamzaq7788@nayapay",
    "rahul.deshpande@okaxis",
    "priya.sharma22@okhdfc",
    "@carlos-r-tx",
    "0300-1234567",
    "+92-300-1234567",
    "03001234567",
    "0333-1234567",
    "0345 9876543",
    "(0315) 1234567",
    "+44 7700 900123",
    "07700 900123",
    "+1 (512) 555-0148",
    "416-555-0177",
    "+91 98220 43210",
    "+49 151 98765432",
    "+1 888-221-1161",
    "PK36SCBL0000001123456702",
    "PK91NAYA0000003001234567",
    "GB29 NWBK 6016 1331 9268 19",
    "de89 3704 0044 0532 0130 00",
    "DE89370400440532013000",
    "DE98ZZZ09999999999",
    "0011223344556677",
    "55667788",
    "000456789012",
    "4411223",
    "532013000",
    "50100987654321",
    "8899-0011-2233-4455",
    "99887766",
    "7712003456",
    "200334455667",
    "88123456700021",
    "40012345678901",
    "170023456789",
    "****6677",
    "42201-7654321-3",
    "078-05-1120",
    "046454286",
    "AB123456C",
    "ABCDP1234F",
    "4111-2222-3333",
    "12 345 678 903",
    "411240012",
    "40-22-19",
    "402219",
    "021000021",
    "30800",
    "37040044",
    "SVBL0001234",
    "NWBKGB2LXXX",
    "COBADEFFXXX",
    "SBIN0011223",
    "SCBLPKKA",
    "SADAPKKA",
    "NAYAPKKA",
    "House B-47",
    "Flat 3, 82 Church Lane",
    "1180 Willow Creek",
    "2210 Lakeshore",
    "Bergmannstraße 44",
    "14/2 MG Road",
    "20260401778812",
    "240930066601122334",
    "662209118845",
    "091000019992213",
    "SR-20260501-000341",
    "PP-D-1122334455",
    "8XJ22190T7002841M",
    "4PL80331B2114902K",
    "1MC55672H9330217N",
    "9RT10448V5567823Q",
    "W-88213345",
    "44120933",
    "402-8871253-1123456",
    "GFP-2026-0412",
    "FEE-APR26-9981",
    "CRES2604020014561234567890123",
    "MEZ4491",
    "P-114488-202600",
    "CRES-b112",
    "SADA-77c3",
    "NAYA-45f8",
    "39.51.202.114",
    "bilalhk91",
    "xxxx445",
    "SadaPay-7703",
    "MCB-9911",
    "Meezan-3312",
    "Crescent-6702",
    "Bank-8834",
]

SAFE = [
    "Bilal Hassan Khan",
    "Foodpanda",
    "NETFLIX.COM",
    "TESCO STORES",
    "PKR185,000.00",
    "+£2,450.00",
    "₹1,12,340.00",
    "01 Apr 2026",
    "Card xxxx8821",
    "Visa x-2070",
    "521234******2070",
    "Daraz.pk",
    "Netflix.com",
]


def test_sample_files_have_no_known_pii(sample_paths):
    extracted = [extract_path(path) for path in sample_paths]
    scrubbed = [scrub_text(item.text) for item in extracted]
    combined = combine_files(
        [
            type(item)(
                filename=item.filename,
                format=item.format,
                text=result.text,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                page_count=item.page_count,
                warnings=item.warnings,
            )
            for item, result in zip(extracted, scrubbed, strict=False)
        ]
    )
    for value in KNOWN_PII:
        assert value not in combined, f"Leaked PII: {value!r}"
    for value in SAFE:
        assert value in combined, f"Over-scrubbed safe value: {value!r}"
    assert scan_residual(combined) == []
    for result in scrubbed:
        assert result.residual == []
        assert_clean(result)


def test_idempotent():
    text = (
        "Customer Name: Bilal Hassan Khan\n"
        "IBAN: PK36SCBL0000001123456702\n"
        "Email: bilal.hkhan91@gmail.com\n"
        "Phone: +92-300-1234567\n"
        "03 Apr 2026 | Paid to Foodpanda Karachi PK | -1240.50 | 7210.00\n"
    )
    first = scrub_text(text)
    second = scrub_text(first.text)
    assert first.text == second.text
    assert "Bilal Hassan Khan" in first.text
    assert "Foodpanda" in first.text
    assert "1240.50" in first.text
    assert "03 Apr 2026" in first.text


def test_merchant_urls_and_masked_cards_survive():
    text = (
        "Paid to Netflix.com Amsterdam NLD Card xxxx2070\n"
        "Linked Card: Visa x-2070 (expires 09/28)\n"
        "Linked Card: 521234******2070\n"
    )
    result = scrub_text(text)
    assert "Netflix.com" in result.text
    assert "xxxx2070" in result.text
    assert "Visa x-2070" in result.text
    assert "521234******2070" in result.text
    assert "09/28" not in result.text


def test_residual_guard_blocks_raw_pii():
    result = scrub_text("Email: leak@example.com")
    assert result.residual == []
    assert "leak@example.com" not in result.text
    # If a detector is bypassed, the residual scanner must still catch it.
    from app.services.scrubber.residual import scan_residual as scan

    assert scan("Email: leak@example.com")
    with pytest.raises(ResidualPIIError):
        assert_clean(type(result)(text=result.text, residual=[{"entity_type": "EMAIL"}]))
