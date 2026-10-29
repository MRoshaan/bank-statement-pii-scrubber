# Demo script — Bank Statement PII Scrubber

Target length: 7–9 minutes. Record at 1080p. Keep the browser at a readable zoom (110–125%).

## Before recording

```bash
cd bank-statement-pii-scrubber
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>.

Have a second terminal ready:

```bash
docker exec -it pj-bank-db psql -U pjbank -d pjbank
```

## Shot list

### 0:00–0:35 — Intro

- State the goal: scrub PII locally, store scrubbed data in PostgreSQL, analyze with Groq, chat with grounded answers.
- Show the privacy banner: raw files stay on this machine.
- Briefly show the four sample files in `data/`.

### 0:35–1:15 — Architecture

- Show `README.md` architecture diagram or the running app.
- Explain:
  - FastAPI endpoint accepts PDF/DOCX/CSV/TXT.
  - Extraction and scrubbing happen in memory.
  - Only scrubbed text and facts reach PostgreSQL/Groq.
  - PostgreSQL stores no raw statement text.
  - Groq gets facts + a scrubbed excerpt + transaction digest.

### 1:15–1:50 — PostgreSQL baseline

In the psql terminal:

```sql
\dt
select count(*) from batches;
select count(*) from transactions;
```

Show that the tables exist and the counts are empty or show one demo batch.

### 1:50–3:10 — Upload and scrub through the frontend

- Drag/select all four files:
  - `crescent_bank_statement_apr2026.pdf`
  - `international_bank_statements_apr2026.docx`
  - `paypal_activity_apr2026.txt`
  - `wallet_transactions.csv`
- Enter a batch name, click **Scrub & store**.
- Show:
  - “Stored in PostgreSQL”
  - 4 files, 119 transactions, redaction count
  - Combined output with `---- File: ... ----` headers
  - Per-file output
  - Redaction table (IBAN, EMAIL, PHONE, NATIONAL_ID, REFERENCE, etc.)
- In the combined output, point out that names/merchants/amounts/dates remain, e.g. `Bilal Hassan Khan`, `Foodpanda`, `NETFLIX.COM`, `PKR 185,000.00`.
- Optional: search the combined output for a known identifier such as the account holder's email or the first IBAN; show it is absent.

### 3:10–4:05 — PostgreSQL proof

Back in psql:

```sql
select id, name, file_count, created_at from batches;
select filename, format, redaction_counts from statement_files order by filename;
select count(*) as transactions, count(distinct currency) as currencies from transactions;
select currency, count(*), round(sum(abs(amount))::numeric,2) as spend
from transactions where amount < 0
group by currency order by spend desc;
select category, count(*), round(sum(abs(amount))::numeric,2) as total
from transactions where amount < 0 and currency = 'PKR'
group by category order by total desc limit 10;
```

Point out that the stored columns are scrubbed text and structured facts; there is no raw-statement column.

### 4:05–5:35 — Groq analysis

- Click **Generate analysis**.
- Show the model badge (`openai/gpt-oss-120b`), grounded status, summary, spending-by-currency table, top categories, top merchants, insights, anomalies, recommendations, and the grounding report.
- Explain the hallucination strategy:
  - Python computes totals.
  - LLM writes narrative only.
  - Citations are re-grounded to matching transactions.
  - Numeric claims are checked against allowed facts.
  - The 8K TPM free-tier limit is handled with a compact facts pack + scrubbed excerpt + digest.

### 5:35–7:00 — Chat

Ask:

1. `How much did I spend on food?`
2. `Which merchant did I pay most often?`

For each answer, show:
- the answer,
- the “Grounded” badge,
- the citation chips,
- the chat session.

Then click **New chat** and ask one more:

3. `What were my largest cash withdrawals?`

Mention that chat input is scrubbed before storage/sending and answers use only facts + retrieved rows.

### 7:00–8:15 — Approach, research, limitations

- Research: compared Presidio/scrubadub/NER/LLM redaction; rejected over-redaction, heavy models, nondeterminism.
- Chose deterministic labeled rules + validators + residual scan.
- Chose PostgreSQL normalization: batches/files/redactions/transactions/analyses/chat.
- Chose `openai/gpt-oss-120b` for free-tier reasoning and JSON support.
- Limitations: no OCR for scanned PDFs, label-dependent addresses, rare ID formats, no FX conversion, token-budgeted analysis.
- One improvement with more time: OCR + per-country rule packs + Alembic/background jobs.

### 8:15–8:30 — Close

- Show the GitHub link in `README.md`.
- Show `outputs/scrubbed_combined.txt` and the redaction report.
- State that the raw files never left the machine and only scrubbed data was sent to Groq.

## Commands for the terminal shots

```bash
# Health
curl -s http://127.0.0.1:8000/api/v1/health

# Optional: create a batch from the CLI
.venv/bin/python -m app.cli scrub data --out outputs --store

# Test suite
.venv/bin/pytest -q
```

## Recording tips

- Do not show `.env` or the Groq key.
- Do not show the raw `data/` contents on screen longer than necessary; the files are synthetic test data, but the privacy story is stronger if the video focuses on the scrubbed output.
- If a Groq call hits a 429, wait a few seconds and retry; the app falls back to deterministic answers for common aggregates.
- Keep the video unlisted/public on Loom or Google Drive and put the link in the reply email and `README.md`.
