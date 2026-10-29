# PJ Bank API — Privacy-first statement analysis

A local-first FastAPI service that scrubs personal and financial identifiers from bank statements, stores the scrubbed data in PostgreSQL, and uses a Groq-hosted LLM for budgeting analysis and grounded chat.

**Public repository:** https://github.com/MRoshaan/pj-bank-api

**Demo video:** _Add your Loom/Drive link here before submitting._

---

## Why this exists

Bank statements contain exactly the data an LLM needs for budgeting analysis — and exactly the data that must not leave the user's machine. This service separates the two:

1. Raw PDF/DOCX/CSV/TXT files are processed **in memory**.
2. A deterministic local scrubber replaces identifiers with placeholders.
3. Only scrubbed text and deterministic facts are stored and sent to Groq.
4. Every LLM payload is re-scanned for residual PII before the request.
5. Chat messages are scrubbed before they are sent or stored.

Raw statement text is never written to PostgreSQL and never sent to Groq.

## Features

- Folder-in, one-string-out scrubber with `---- File: <name> ----` headers.
- PDF (pdfplumber), DOCX (python-docx), CSV/TXT (charset-normalizer), and safe ZIP uploads.
- Deterministic PII detection for:
  - IBANs, account numbers, full card numbers
  - CNIC, SSN, SIN, UK NI, PAN, Aadhaar, tax IDs
  - Emails, phone numbers, UPI/payment handles, wallet IDs
  - Routing/sort/BIC/SWIFT/IFSC/MICR/transit identifiers
  - Long reference, trace, transaction, invoice, order, consumer and statement IDs
  - Home/customer addresses and IP addresses
- Preserves names, merchants (including `Netflix.com`), dates, times, amounts, balances, currencies, and transaction descriptions.
- Keeps masked card last-4 (`xxxx2070`); removes masked bank/wallet identifiers.
- PostgreSQL schema for batches, files, redactions, transactions, analyses, and chat history.
- Groq analysis with deterministic facts, structured JSON, citation grounding, and numeric validation.
- Grounded chat with retrieval, citations, and deterministic fallback for common aggregate questions.
- Vanilla HTML/CSS/JS frontend. The UI renders Pakistani rupees with `₨`; the API, database, and LLM keep ISO `PKR` for precision.
- 21 automated tests covering leaks, precision, API flow, and guardrails.

## Architecture

```text
Browser (vanilla JS)
        |
        v
FastAPI /api/v1
        |
        +-- extract PDF/DOCX/CSV/TXT in memory
        +-- local deterministic scrubber
        +-- residual-PII guard
        +-- transaction parser + deterministic facts
        |
        v
PostgreSQL (scrubbed text, files, redactions, transactions, analyses, chats)
        |
        v
Groq openai/gpt-oss-120b
   analysis: compact facts + scrubbed excerpt + transaction digest
   chat:     facts + retrieved scrubbed rows + validated analysis
```

## Quick start

### 1. Prerequisites

- Python 3.12+
- Docker (for PostgreSQL 16)
- A Groq API key from [console.groq.com](https://console.groq.com)

### 2. Install

```bash
git clone https://github.com/MRoshaan/pj-bank-api.git
cd pj-bank-api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set `GROQ_API_KEY`. The key is never committed.

### 3. Start PostgreSQL

The host used for development does not have the Docker Compose plugin, so the tested command is `docker run`:

```bash
docker run --name pj-bank-db \
  -e POSTGRES_USER=pjbank \
  -e POSTGRES_PASSWORD=pjbank_dev_password \
  -e POSTGRES_DB=pjbank \
  -p 5432:5432 \
  -v pjbank_pgdata:/var/lib/postgresql/data \
  -d postgres:16
```

A `docker-compose.yml` is included for environments that have Compose.

Create the test database and tables:

```bash
docker exec pj-bank-db psql -U pjbank -d postgres -c "CREATE DATABASE pjbank_test;" || true
.venv/bin/python scripts/init_db.py
```

### 4. Run

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. API docs are at <http://127.0.0.1:8000/docs>.

### 5. CLI: folder in, one string out

Place the provided `data/` folder in the project root (it is intentionally not committed), then:

```bash
.venv/bin/python -m app.cli scrub data --out outputs --name "Provided sample statements" --store
```

Outputs:

```text
outputs/scrubbed_combined.txt      # one combined string with per-file headers
outputs/per_file/*.scrubbed.txt    # per-file scrubbed output
outputs/redaction_report.json      # counts/types, no original values
outputs/transactions.json
outputs/facts.json
outputs/metadata.json
```

`--store` persists the batch to PostgreSQL. Omit it to generate files only.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/batches` | Multipart upload; scrub, parse, store |
| `GET` | `/api/v1/batches` | Recent batches |
| `GET` | `/api/v1/batches/{id}` | Batch detail |
| `GET` | `/api/v1/batches/{id}/scrubbed` | Combined scrubbed text download |
| `GET` | `/api/v1/batches/{id}/transactions` | Filter by category/merchant |
| `POST` | `/api/v1/batches/{id}/analyze` | Generate Groq analysis |
| `GET` | `/api/v1/batches/{id}/analysis` | Latest analysis |
| `POST` | `/api/v1/batches/{id}/chat` | Grounded chat |
| `GET` | `/api/v1/batches/{id}/chat/sessions/{sid}` | Chat history |
| `GET` | `/api/v1/health` | DB + Groq configuration |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/batches \
  -F "name=April statements" \
  -F "files=@data/wallet_transactions.csv"
```

## Database schema

| Table | Purpose |
|---|---|
| `batches` | One upload run; combined scrubbed text, counts, facts, warnings |
| `statement_files` | Per-file scrubbed text, hash, format, counts, warnings |
| `redactions` | Entity type + placeholder + count (never original values) |
| `transactions` | Date, time, description, merchant, category, signed amount, currency, balance, source line |
| `analyses` | Model, prompt version, JSON result, markdown, grounding report, usage |
| `chat_sessions` | Conversation per batch |
| `chat_messages` | User/assistant turns, citations, grounding metadata |

All tables use UUID primary keys and cascade deletes. `statement_files.batch_id`, `transactions.batch_id`, `analyses.batch_id`, and chat tables are indexed. Amounts use `NUMERIC(18,2)`, not floats.

`schema.sql` contains the PostgreSQL DDL.

### Why this schema

- Normalizing files and transactions makes per-file output, filtering, and deterministic aggregation possible.
- `transactions` is the source of truth for chat and analysis; the LLM never computes totals.
- `analyses` is versioned by model/prompt so a later run does not overwrite an earlier result.
- `chat_messages` stores citations and grounding metadata for auditability.
- No raw statement column exists. That is deliberate.

## Scrubbing approach

The scrubber is a local, span-based rule engine. It combines labeled field detection, format validation, and context checks, then resolves overlapping spans by priority before replacing them. This avoids a common failure mode where one regex corrupts another rule's placeholder.

Key decisions:

- **No Presidio, spaCy NER, scrubadub, or LLM in the scrubbing path.** Those tools over-redact person names, which the task requires preserving, and add nondeterminism/heavy models.
- **Validators, not just regex:** IBAN mod-97, Luhn cards, `phonenumbers` for international phone formats, date/timestamp exclusions, amount-context exclusions.
- **Precision guard:** merchant URLs (`Netflix.com`, `Amazon.co.uk`) stay; only emails/handles are removed.
- **Fail closed:** after scrubbing, a high-confidence residual scanner runs. If it finds PII, the batch is blocked before any LLM call.
- **Idempotent placeholders:** scrubbing an already-scrubbed file does not change it.

### Known limitations

- Scanned PDFs without a text layer are not OCR'd; the file is flagged with a warning.
- Addresses are label-driven (`Address:`, `Anschrift:`, etc.). An unlabeled free-text address may survive.
- Very unusual national-ID formats or statement layouts may need a new labeled rule.
- Multi-currency statements are reported per currency; there is no FX conversion.
- The transaction parser covers the provided layouts and common variants, not every bank's format.
- The free Groq tier has an 8K TPM limit, so analysis sends a compact facts pack, a 3K-character scrubbed excerpt, and a complete transaction digest rather than the entire combined string.

## Groq analysis and chat

- Model: `openai/gpt-oss-120b`, fallback `openai/gpt-oss-20b`.
- Why: available on Groq's free tier, 131K context, strong reasoning, JSON mode, ~500 tokens/sec. The older Llama 3.3 70B is no longer on the free/developer tier; Qwen 3.8 27B is preview and more expensive.
- Analysis output is structured JSON: summary, insights, anomalies, recommendations, data-quality notes.
- Deterministic Python facts are the only source of truth for numbers.
- Every numeric claim and citation is validated. Invalid citations are filtered/re-grounded; unsupported numbers trigger one repair retry, then a deterministic fallback.
- Chat retrieves relevant scrubbed rows plus facts, bounds history, and validates citations/numbers.
- Common aggregate questions have deterministic fallbacks, so a model/rate-limit failure does not produce an ungrounded answer.
- Prompt injection is treated as data: statement text and retrieved rows are delimited and never followed as instructions.

See `NOTES.md` for the four required LLM write-ups and `docs/GUARDRAILS.md` for tests.

## Testing

```bash
.venv/bin/pytest -q
.venv/bin/ruff check app tests
```

The suite covers:
- all four sample formats and the combined output
- known-PII absence and merchant/amount/date preservation
- idempotence, masked cards, merchant URLs
- transaction parsing, Indian/German number formats, PayPal totals
- API upload → DB → analysis → chat
- prompt injection, residual-PII blocking, numeric/citation validation

## Project layout

```text
app/                  FastAPI app, scrubber, parser, facts, Groq clients
frontend/             vanilla HTML/CSS/JS
tests/                pytest suite
outputs/              scrubbed output and reports
docs/                 demo script, guardrails, AI transcript/tool notes
scripts/init_db.py    create tables
AGENTS.md             rules for future coding agents
schema.sql            PostgreSQL DDL
```

## Demo

Run the app, upload the four provided files, inspect the combined/per-file output, query PostgreSQL, generate the analysis, and ask:

- “How much did I spend on food?”
- “Which merchant did I pay most often?”

A shot-by-shot script is in `docs/DEMO_SCRIPT.md`.

## Approach and limitations (short version)

The service treats scrubbing as a local security boundary, not a prompt-engineering problem. A deterministic, label-aware engine removes identifiers while preserving analytical context; PostgreSQL stores only scrubbed text and structured transactions; Groq turns deterministic facts into narrative and grounded chat. The main trade-offs are no OCR for scanned PDFs, label-dependent address detection, per-currency rather than converted totals, and a token-budgeted analysis prompt forced by Groq's free-tier TPM limit.

## License

MIT. See `LICENSE`.
