# NOTES — PJ Bank API

## Research and alternatives

I evaluated Microsoft Presidio, scrubadub, spaCy NER, and LLM-based redaction. All were rejected as the primary engine: Presidio/scrubadub/LLM redaction over-scrub person names, which the brief requires preserving, and NER adds a heavy model plus nondeterminism. I chose a local, deterministic span-based engine using labeled context, IBAN mod-97, Luhn, `phonenumbers`, and date/amount exclusions. Python-docx, pdfplumber (MIT; PyMuPDF is AGPL), and charset-normalizer cover the formats. The scrubber preserves masked card last-4 but removes masked bank/wallet identifiers, keeps merchant URLs, and fails closed on residual PII.

## API and database

The API is resource-oriented: `POST /api/v1/batches` performs upload → in-memory extraction → scrub → parse → persist atomically. Keeping scrubbing inside the create action means raw text is never written to a staging table. Subresources expose scrubbed text, transactions, analysis, and chat sessions. Folder processing is a CLI, not an HTTP path parameter, to avoid exposing server filesystem paths.

PostgreSQL normalizes `batches`, `statement_files`, `redactions`, `transactions`, `analyses`, `chat_sessions`, and `chat_messages`. The `transactions` table is the deterministic source of truth for chat/analysis; `analyses` is versioned by model/prompt; `redactions` stores counts and placeholders only, never originals. No raw statement column exists. UUIDs, `NUMERIC(18,2)`, JSONB for flexible facts/reports, and cascade deletes keep the schema auditable and safe.

## LLM model

I chose `openai/gpt-oss-120b` on Groq's free tier: 131K context, 30 RPM/1K RPD/8K TPM/200K TPD, strong reasoning, JSON mode, ~500 tokens/sec. `gpt-oss-20b` is faster but weaker; Qwen 3.8 27B is preview and higher-cost; Llama 3.3 70B left the free/developer tier in August 2026. The 8K TPM limit is why analysis sends a compact facts pack, a 3K-character scrubbed excerpt, and a complete transaction digest, not the full combined corpus. Chat uses facts plus retrieved rows, not the whole statement.

## System prompt

The analysis system prompt defines the role, treats statement text as untrusted data, makes FACTS the only source of truth for numbers, forbids invented transactions/amounts, requires per-currency reporting, requires transaction refs, and specifies a strict JSON schema. Chat uses the same rules plus “refuse when the context is insufficient” and a JSON answer/citations/figures schema. Output is parsed with Pydantic; invalid JSON gets one repair attempt.

## Hallucination and accuracy

Python computes all totals, category sums, merchant rankings, balances, fees, cash, and transfers. The LLM writes narrative only. After generation, a deterministic citation-grounding pass replaces model-chosen refs with rows that match the claim’s category/merchant/currency, and every currency/decimal/percentage claim is checked against the allowed fact values. Invalid citations are filtered; unsupported numbers trigger one repair retry, then a deterministic facts-based fallback. Chat has deterministic fallbacks for food/category spend, top merchant, total spend, fees, cash, transfers, and income. Common capture errors are also handled: the PDF’s split IBAN, masked card vs. bank account, `Netflix.com` vs. email, dates/timestamps vs. long refs, and Indian/German amount formats.

## Guardrails and testing

Every Groq payload is re-scanned by the residual-PII detector immediately before the call; chat input is scrubbed before storage/sending; LLM output is scrubbed and scanned before display. Statement data is delimited and never followed as instructions. Additional guards: upload size/type limits, zip-slip protection, JSON schema validation, token/history bounds, 429/5xx retry with model fallback, no raw-text logging. `pytest` covers known-PII absence, merchant/amount/date preservation, idempotence, all four formats, transaction parsing, API flow, prompt injection, residual-PII blocking, numeric/citation validation, and deterministic fallbacks: **21 tests pass**.

## Limitations and next steps

No OCR for scanned PDFs; addresses depend on labels; rare ID formats/layouts need new rules; no FX conversion; parser coverage is not universal. With more time I would add OCR, a labeled-address model, per-country rule packs, Alembic migrations, background analysis jobs, and a larger adversarial evaluation set. The video and README cover the end-to-end flow; the AI transcript and `prompts.txt` disclose tool usage with PII and the API key redacted.
