from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import ChatMessage, ChatSession, StatementFile, Transaction
from app.services.llm.client import GroqLLM, LLMError, LLMResult
from app.services.llm.context import allowed_numbers, validate_chat_payload, validate_payload
from app.services.pipeline import PipelineError, process_sources

CSV = (
    b"TIMESTAMP,TYPE,DESCRIPTION,AMOUNT,BALANCE\n"
    b"2026-04-01 12:00:00,Payment,Foodpanda,-100.00,900.00\n"
    b"2026-04-02 12:00:00,Payment,Netflix.com,-20.00,880.00\n"
)


def analysis_payload(summary="A summary from the statement."):
    return {
        "summary": summary,
        "insights": [{"title": "Food", "detail": "Review food spending.", "evidence_refs": []}],
        "recommendations": [{"title": "Budget", "detail": "Review category budgets.", "evidence_refs": []}],
        "anomalies": [],
        "data_quality_notes": [],
    }


def fake_llm(data):
    return SimpleNamespace(complete_json=Mock(return_value=LLMResult(data=data, model="fake", usage={})))


@pytest.fixture()
def batch_id(client):
    response = client.post("/api/v1/batches", files=[("files", ("bank.csv", CSV))])
    assert response.status_code == 201, response.text
    return response.json()["batch"]["id"]


def test_analysis_scrubs_all_output_fields(client, batch_id, monkeypatch):
    data = analysis_payload("Contact leak@example.com for a summary.")
    data["insights"][0]["title"] = "Write to leak@example.com"
    data["data_quality_notes"] = ["Email: leak@example.com"]
    monkeypatch.setattr("app.services.llm.analysis.GroqLLM", lambda: fake_llm(data))
    response = client.post(f"/api/v1/batches/{batch_id}/analyze")
    assert response.status_code == 201
    assert "leak@example.com" not in response.text
    assert response.json()["status"] == "completed"
    assert "<EMAIL>" in response.json()["result"]["summary"]


def test_failed_analysis_grounding_uses_fallback(client, batch_id, monkeypatch):
    llm = fake_llm(analysis_payload("You spent 987654.32 PKR."))
    monkeypatch.setattr("app.services.llm.analysis.GroqLLM", lambda: llm)
    response = client.post(f"/api/v1/batches/{batch_id}/analyze")
    assert response.status_code == 201
    assert response.json()["status"] == "fallback"
    assert response.json()["grounding_report"]["grounded"] is True
    assert "987654.32" not in json.dumps(response.json()["result"])


def test_analysis_schema_error_does_not_echo_model_pii(client, batch_id, monkeypatch):
    llm = fake_llm({"summary": {"email": "leak@example.com"}})
    monkeypatch.setattr("app.services.llm.analysis.GroqLLM", lambda: llm)
    response = client.post(f"/api/v1/batches/{batch_id}/analyze")
    assert response.status_code == 201
    assert "leak@example.com" not in response.text
    for call in llm.complete_json.call_args_list:
        assert "leak@example.com" not in call.kwargs["user"]


@pytest.mark.parametrize("source", ["history", "analysis"])
def test_chat_scans_complete_prompt(client, batch_id, monkeypatch, source):
    llm = fake_llm({"answer": "A safe answer.", "grounded": True})
    monkeypatch.setattr("app.services.llm.chat.GroqLLM", lambda: llm)
    session_id = None
    with SessionLocal() as db:
        if source == "history":
            session = ChatSession(batch_id=batch_id, title="Legacy conversation")
            db.add(session)
            db.flush()
            session_id = str(session.id)
            db.add(ChatMessage(session_id=session.id, role="assistant", content="Email: leak@example.com"))
        else:
            from app.models import Analysis
            db.add(Analysis(batch_id=batch_id, model="legacy", result=analysis_payload("Email: leak@example.com")))
        db.commit()
    response = client.post(
        f"/api/v1/batches/{batch_id}/chat",
        json={"message": "How much did I spend?", "session_id": session_id},
    )
    assert response.status_code == 422
    llm.complete_json.assert_not_called()


def test_chat_scrubs_refusal_and_figure_metadata(client, batch_id, monkeypatch):
    data = {
        "answer": "Spending is in the facts.",
        "figures": [{"value": 100, "label": "Email: leak@example.com"}],
        "refusal": "Email: leak@example.com",
        "grounded": True,
    }
    monkeypatch.setattr("app.services.llm.chat.GroqLLM", lambda: fake_llm(data))
    response = client.post(f"/api/v1/batches/{batch_id}/chat", json={"message": "Review my budget."})
    assert response.status_code == 200
    assert "leak@example.com" not in response.text
    with SessionLocal() as db:
        message = db.query(ChatMessage).filter(ChatMessage.session_id == response.json()["session_id"], ChatMessage.role == "assistant").one()
        assert "leak@example.com" not in json.dumps(message.grounding)


def test_transport_blocks_pii_even_when_caller_omits_preflight(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key-not-used")
    llm = GroqLLM()
    create = Mock()
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(LLMError):
        llm._call("fake", "A safe system prompt.", "Email: leak@example.com", 100, 0)
    create.assert_not_called()


@pytest.mark.parametrize("claim", ["999 PKR", "PKR 999", "-999 PKR", "999 transactions", "999%", "PKR999", "999PKR", "cost:999", "-999.00 PKR"])
def test_integer_and_signed_claims_are_checked(claim):
    assert validate_payload(analysis_payload(f"You spent {claim}."), set(), {100.0})["grounded"] is False


def test_arbitrary_small_amounts_are_not_whitelisted():
    assert 37.0 not in allowed_numbers({})
    assert validate_payload(analysis_payload("Spend PKR 37."), set(), allowed_numbers({}))["grounded"] is False


def test_chat_honors_model_refusal():
    report = validate_chat_payload({"answer": "Insufficient context.", "grounded": False, "refusal": "Unknown."}, set(), set())
    assert report["grounded"] is False


def test_duplicate_filenames_keep_distinct_sources(client):
    response = client.post(
        "/api/v1/batches",
        files=[("files", ("bank.csv", CSV)), ("files", ("folder/bank.csv", CSV.replace(b"Foodpanda", b"KFC")))],
    )
    assert response.status_code == 201
    body = response.json()
    assert len({file["filename"] for file in body["files"]}) == 2
    with SessionLocal() as db:
        files = db.query(StatementFile).filter(StatementFile.batch_id == body["batch"]["id"]).all()
        assert all(db.query(Transaction).filter(Transaction.file_id == file.id).count() == 2 for file in files)
        refs = [row.meta["ref"] for row in db.query(Transaction).filter(Transaction.batch_id == body["batch"]["id"])]
        assert len(set(refs)) == 4


def test_filename_and_batch_name_are_scrubbed(client):
    response = client.post(
        "/api/v1/batches",
        files=[("files", ("leak@example.com.csv", CSV))],
        data={"name": "Email: leak@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "leak@example.com" not in response.text
    assert body["batch"]["transaction_count"] == 2


def zip_bytes(entries):
    import io
    import zipfile

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


def test_zip_expansion_enforces_file_count(client, monkeypatch):
    monkeypatch.setattr(settings, "max_files", 1)
    response = client.post(
        "/api/v1/batches",
        files=[("files", ("statements.zip", zip_bytes([("a.csv", CSV), ("b.csv", CSV)])))],
    )
    assert response.status_code == 413


def test_zip_expansion_enforces_total_size(client, monkeypatch):
    monkeypatch.setattr(settings, "max_total_mb", 1)
    archive = zip_bytes([("a.txt", b"x" * 600_000), ("b.txt", b"x" * 600_000)])
    response = client.post("/api/v1/batches", files=[("files", ("statements.zip", archive))])
    assert response.status_code == 413


def test_corrupt_zip_is_a_pipeline_error():
    with pytest.raises(PipelineError):
        process_sources([("bad.zip", b"not a zip")])


def test_negative_balance_is_preserved():
    from app.services.transactions import parse_transactions
    parsed = parse_transactions("bank.txt", "01 Apr 2026 | Paid to Foodpanda PKR -100.00 -50.00")
    assert len(parsed.records) == 1
    assert parsed.records[0].balance == -50


def test_analysis_fallback_handles_no_transactions(client, monkeypatch):
    response = client.post("/api/v1/batches", files=[("files", ("empty.txt", b"No transactions in this statement."))])
    assert response.status_code == 201
    llm = fake_llm({})
    monkeypatch.setattr("app.services.llm.analysis.GroqLLM", lambda: llm)
    analysis = client.post(f"/api/v1/batches/{response.json()['batch']['id']}/analyze")
    assert analysis.status_code == 201
    assert analysis.json()["status"] == "fallback"


def test_reference_ids_are_blocked_at_transport_boundary():
    from app.services.llm.client import LLMPrivacyError, ensure_safe_prompt
    with pytest.raises(LLMPrivacyError):
        ensure_safe_prompt("Safe instructions.", "Transaction ID: 1234567890123")


def test_duplicate_detection_keeps_currencies_separate():
    from dataclasses import replace

    from app.services.facts import build_facts
    from app.services.transactions import parse_transactions

    first = parse_transactions("bank.txt", "01 Apr 2026 | Foodpanda PKR -100.00 900.00").records[0]
    second = replace(first, filename="other.txt", currency="USD")
    facts = build_facts([first, second], [])
    assert facts["duplicate_groups"] == []


def test_unknown_filename_suffix_is_scrubbed():
    result = process_sources([("bank.+92-300-1234567", CSV)])
    assert "+92-300-1234567" not in result.combined_text


def test_provider_response_without_usage_is_supported(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key-not-used")
    llm = GroqLLM()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer":"OK"}'))], usage=None)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))
    assert llm._call("fake", "Safe instructions.", "Safe question.", 100, 0).usage == {}


def test_non_object_model_json_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key-not-used")
    llm = GroqLLM()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))], usage=None)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response))))
    with pytest.raises(LLMError, match="not an object"):
        llm._call("fake", "Safe instructions.", "Safe question.", 100, 0)


def test_date_shaped_transfer_reference_is_removed():
    from app.services.scrubber.engine import scrub_text
    result = scrub_text("RAAST FT - Digital 20260402001456 FT to Ali")
    assert "20260402001456" not in result.text
    assert "Ali" in result.text


def test_compact_timestamp_field_survives():
    from app.services.scrubber.engine import scrub_text
    text = "Timestamp: 20260402001456 transfer to Ali"
    assert scrub_text(text).text == text


def test_residual_references_preserve_serialized_dates_and_totals():
    from app.services.scrubber.residual import scan_residual
    text = '{"ref":"bank.csv:1","date":"2026-04-03","transfers":{"amount":229850.0}}'
    assert scan_residual(text) == []


def test_adjacent_amount_columns_parse_separately():
    from app.services.transactions import parse_transactions
    result = parse_transactions("bank.txt", "01 Apr 2026 | Foodpanda PKR -100.00 900.00")
    assert len(result.records) == 1
    assert result.records[0].amount == -100
    assert result.records[0].balance == 900


def test_calendar_month_year_does_not_become_a_money_claim():
    data = analysis_payload("April 2026 includes spending of PKR 100.")
    assert validate_payload(data, set(), {100.0})["grounded"] is True
    data = analysis_payload("You spent PKR 2026.")
    assert validate_payload(data, set(), {100.0})["grounded"] is False


def test_analysis_prompt_bounds_large_digest():
    from app.services.llm.prompts import build_analysis_prompt
    prompt = build_analysis_prompt({}, "x" * 20_000, "row\n" * 20_000)
    assert len(prompt) < 12_000
    assert "Digest truncated" in prompt


def test_chat_analysis_and_history_are_bounded():
    from app.services.llm.prompts import build_chat_prompt
    data = analysis_payload("x" * 10_000)
    data["insights"] *= 100
    prompt = build_chat_prompt(data, {}, [], [{"role": "user", "content": "y" * 10_000}] * 100, "Review spending.")
    assert len(prompt) < 8_000


def test_chat_receives_requested_category_even_below_top_three(client, monkeypatch):
    csv = CSV + (
        b"2026-04-03 12:00:00,Payment,Careem,-500.00,380.00\n"
        b"2026-04-04 12:00:00,Payment,TESCO,-400.00,-20.00\n"
        b"2026-04-05 12:00:00,Payment,Electric bill,-300.00,-320.00\n"
    )
    response = client.post("/api/v1/batches", files=[("files", ("bank.csv", csv))])
    assert response.status_code == 201
    llm = fake_llm({"answer": "Food spending is in the provided category facts.", "grounded": True})
    monkeypatch.setattr("app.services.llm.chat.GroqLLM", lambda: llm)
    response = client.post(f"/api/v1/batches/{response.json()['batch']['id']}/chat", json={"message": "How much did I spend on food?"})
    assert response.status_code == 200
    prompt = llm.complete_json.call_args.kwargs["user"]
    facts = json.loads(prompt.split("<FACTS>\n", 1)[1].split("\n</FACTS>", 1)[0])
    assert "Food & Dining" not in facts["by_category"]["PKR"]
    assert facts["requested_category"]["by_currency"]["PKR"]["spend"] == 100
