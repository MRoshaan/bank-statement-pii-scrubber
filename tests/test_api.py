from __future__ import annotations

from app.db import SessionLocal
from app.models import ChatMessage, StatementFile


class FakeLLM:
    def complete_json(self, system: str, user: str, max_tokens=None, temperature=None):
        from app.services.llm.client import LLMResult

        if "analysis engine" in system:
            data = {
                "summary": "A concise grounded summary.",
                "insights": [
                    {
                        "title": "Food and dining",
                        "detail": "Food and dining is a recurring category in the scrubbed data.",
                        "evidence_refs": [],
                        "confidence": "high",
                    }
                ],
                "anomalies": [],
                "recommendations": [
                    {
                        "title": "Set a category budget",
                        "detail": "Use the category totals to set a monthly budget.",
                        "evidence_refs": [],
                    }
                ],
                "data_quality_notes": ["Parsed transactions are available."],
            }
        else:
            data = {
                "answer": "Food spending is available in the deterministic facts.",
                "citations": [],
                "figures": [],
                "grounded": True,
                "refusal": None,
            }
        return LLMResult(data=data, model="fake-model", usage={"total_tokens": 1})


def _files(sample_paths):
    return [
        ("files", (path.name, path.read_bytes(), "application/octet-stream"))
        for path in sample_paths
    ]


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["groq_configured"] is True


def test_upload_scrub_store_and_analysis(client, sample_paths, monkeypatch):
    monkeypatch.setattr("app.services.llm.analysis.GroqLLM", lambda: FakeLLM())
    monkeypatch.setattr("app.services.llm.chat.GroqLLM", lambda: FakeLLM())

    response = client.post(
        "/api/v1/batches",
        files=_files(sample_paths),
        data={"name": "API test batch"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    batch = body["batch"]
    assert batch["file_count"] == 4
    assert batch["transaction_count"] == 119
    assert "bilal.hkhan91@gmail.com" not in batch["combined_text"]
    assert "Foodpanda" in batch["combined_text"]
    assert len(body["files"]) == 4

    batch_id = batch["id"]
    detail = client.get(f"/api/v1/batches/{batch_id}")
    assert detail.status_code == 200
    assert detail.json()["transaction_count"] == 119

    transactions = client.get(f"/api/v1/batches/{batch_id}/transactions?category=Food%20%26%20Dining")
    assert transactions.status_code == 200
    assert len(transactions.json()) > 0

    scrubbed = client.get(f"/api/v1/batches/{batch_id}/scrubbed")
    assert scrubbed.status_code == 200
    assert "bilal.hkhan91@gmail.com" not in scrubbed.text

    analysis = client.post(f"/api/v1/batches/{batch_id}/analyze")
    assert analysis.status_code == 201, analysis.text
    analysis_body = analysis.json()
    assert analysis_body["status"] == "completed"
    assert analysis_body["grounding_report"]["grounded"] is True

    chat = client.post(
        f"/api/v1/batches/{batch_id}/chat",
        json={"message": "How much did I spend on food?"},
    )
    assert chat.status_code == 200, chat.text
    chat_body = chat.json()
    assert chat_body["grounded"] is True
    session_id = chat_body["session_id"]

    history = client.get(f"/api/v1/batches/{batch_id}/chat/sessions/{session_id}")
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2

    pii_chat = client.post(
        f"/api/v1/batches/{batch_id}/chat",
        json={"message": "My email is leak@example.com. How much did I spend on food?", "session_id": session_id},
    )
    assert pii_chat.status_code == 200
    db = SessionLocal()
    try:
        messages = db.query(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(4).all()
        assert all("leak@example.com" not in message.content for message in messages)
        files = db.query(StatementFile).filter(StatementFile.batch_id == batch_id).all()
        assert len(files) == 4
        assert all("bilal.hkhan91@gmail.com" not in file.scrubbed_text for file in files)
    finally:
        db.close()


def test_unusable_upload_is_rejected(client):
    response = client.post(
        "/api/v1/batches",
        files=[("files", ("bad.bin", b"\x00\x01\x02\x03", "application/octet-stream"))],
    )
    assert response.status_code == 422
    assert "No files could be processed" in response.text or "Unsupported" in response.text


def test_analysis_requires_existing_batch(client):
    response = client.post("/api/v1/batches/00000000-0000-0000-0000-000000000000/analyze")
    assert response.status_code == 404


def test_list_batches(client):
    response = client.get("/api/v1/batches")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
