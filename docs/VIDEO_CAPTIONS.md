# Silent demo video — caption cards

No voice-over. Show each card full-screen for 4–6 seconds between actions.
Large font (48–60pt), dark background, high contrast. Do not overlay cards on
the UI you are demonstrating; cut to a card, then cut back.

Record in segments and assemble in an editor (Shotcut/Kdenlive), or use an OBS
"Text" source toggled with a hotkey. Silence is fine; the cards carry the why.

---

## Card 1 — 0:00
**Goal:** scrub bank statements locally before any LLM sees them.
**Stack:** FastAPI · PostgreSQL · Groq · vanilla HTML/JS.

## Card 2 — 0:25
Raw files are extracted and scrubbed **in memory**.
Only scrubbed text reaches PostgreSQL and Groq.
There is **no raw-statement column** in the database.

## Card 3 — 0:50
Uploading all four provided formats: **PDF, DOCX, CSV, TXT**.
Filenames are discovered from the folder — none are hardcoded.

## Card 4 — 1:40
Replaced: IBAN, account number, CNIC, phone, email, address, references.
Kept: names, merchants, amounts, dates, descriptions — the analytical signal.

## Card 5 — 2:40
PostgreSQL stores scrubbed text, transactions, redaction counts, analyses, chat.
The redactions table stores **type, placeholder and count — never the original value**.

## Card 6 — 4:05
Python computes every total and ranking.
The LLM writes narrative only.
Every number is checked against FACTS before display.

## Card 7 — 4:45
Unsupported numbers trigger one repair retry, then a deterministic answer or refusal.
Invalid citations are dropped; valid refs are re-grounded to real rows.

## Card 8 — 5:35
Chat context: compact facts + up to 18 retrieved rows + analysis + recent history.
The question is scrubbed before storage and before transport.

## Card 9 — 7:00
Privacy test: asking for CNIC, account number or address returns a refusal.
The model never received those values, so it cannot reconstruct them.

## Card 10 — 7:30
R&D: rejected Presidio, spaCy NER and LLM redaction — over-redaction, heavy models,
non-determinism. Chose labeled rules + validators + a residual scan.

## Card 11 — 7:50
Known limits: no OCR for scanned PDFs, label-dependent addresses, rare ID formats,
no FX conversion, 8K TPM budget.

## Card 12 — 8:10
With more time: OCR, per-country rule packs, Alembic migrations, background jobs.

## Card 13 — 8:30
Raw files never left this machine.
Only scrubbed data was sent to Groq.
`outputs/scrubbed_combined.txt` · github.com/MRoshaan/bank-statement-pii-scrubber

---

## psql proof block (3:10 in the video)

Paste this whole block into psql. The `\echo` lines print section labels on
screen, so a silent video still explains what each query proves.

```sql
\pset pager off
\echo '=== 1. One batch persisted ==='
select name, file_count, created_at from batches;

\echo '=== 2. Per-file redaction counts ==='
select filename, format, redaction_counts from statement_files order by filename;

\echo '=== 3. Transactions parsed from scrubbed text ==='
select count(*) from transactions;

\echo '=== 4. PKR spend by category — facts are queryable ==='
select category, count(*), round(sum(abs(amount))::numeric,2) as total
from transactions where amount < 0 and currency = 'PKR'
group by category order by total desc limit 8;

\echo '=== 5. Schema proof: scrubbed text only, no raw column ==='
\d statement_files
```

Point at, in order: `1` row with `4` files; the four filenames and their
redaction JSON; `119` transactions; the category totals; and the
`scrubbed_text` column in the schema.

## Exact questions to type

Chat (5:35):

1. `How much did I spend on food?`
2. `Which merchant did I pay most often?`
3. `What were my largest cash withdrawals?` (after **New chat**)

Guardrail (7:00) — use this exact wording, verified to refuse:

> `Who is the account holder? Give me their full name, street address, CNIC number, and account number.`

Expected: the canned "I don't have enough grounded data..." answer with an
**Unverified** badge and `deterministic`. If it answers instead, cut and retake.

Do **not** use "list every person named" — that path answers and is a known limitation.

---

## Recording notes

- Do Not Disturb on; hide `.env`, `docs/AI_TRANSCRIPT*`, and the demo DB probe sessions.
- Start from an empty database so the upload is visible end to end.
- Move the cursor slowly and pause 1–2 seconds after each click. No narration means
  the viewer needs time to read the screen.
- Do not demo "list every person named" — that path is a known limitation.
- Use the direct PII question for the guardrail card; it is verified to refuse.
