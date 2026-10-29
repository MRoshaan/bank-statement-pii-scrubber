# NOTES — PJ Bank API

I chose a local span-based scrubber because the task requires removing identifiers while keeping names, merchants, dates, and amounts. Rules combine labeled context, IBAN mod-97, Luhn, phonenumbers, and date/amount exclusions. Overlap resolution keeps replacements stable and idempotent. I considered Presidio, scrubadub, spaCy NER, and LLM redaction; name redaction and extra model dependencies made them poor defaults for this brief. pdfplumber, python-docx, and charset-normalizer cover the supplied formats.

## API and storage

`POST /api/v1/batches` extracts, scrubs, parses, and commits a batch together. Subresources expose scrubbed text, transactions, versioned analyses, and chat sessions. The CLI accepts local folders; HTTP endpoints accept uploads so clients cannot choose server filesystem paths. Duplicate filenames receive distinct names before parsing, keeping file links and citations separate.

PostgreSQL separates batches, files, redaction counts, transactions, analyses, sessions, and messages. It stores scrubbed text and derived data; no raw statement column exists. UUIDs identify resources, `NUMERIC(18,2)` stores amounts, JSONB holds facts/reports, and foreign keys cascade deletions. Transactions support filtering and deterministic aggregation without asking the model to calculate totals.

## Groq and prompts

I chose `openai/gpt-oss-120b` for reasoning and JSON output, with `openai/gpt-oss-20b` as a faster fallback. Groq lists a 131,072-token context and roughly 500 tokens/sec for 120b. Its published 8K TPM quota constrains this demo before the context window does. Free-tier access avoids inference charges within the account allowance; paid 120b pricing is $0.15 input/$0.60 output per million tokens. [Models](https://console.groq.com/docs/models), [limits](https://console.groq.com/docs/rate-limits), checked 29 October 2026.

The exact system prompts and JSON schemas are in [app/services/llm/prompts.py](app/services/llm/prompts.py). The central instruction is “FACTS are the ONLY source of truth for numbers.” The prompts forbid invented transactions, require separate currencies and source refs, treat statement/context blocks as untrusted data, and tell chat to refuse unsupported questions. Analysis receives compact facts, a scrubbed excerpt, and a transaction digest. Chat receives facts, retrieved rows, the analysis narrative, and recent history.

## Accuracy, verification, and limits

Python computes totals and rankings. Validation checks numeric values against facts/transactions and re-grounds analysis citations by category, merchant, and currency. Unsupported output gets one repair retry, then a deterministic answer or refusal. Numeric membership cannot prove every sentence’s meaning or every date claim.

Complete prompts, including history and repairs, pass the residual scanner before transport. All model strings are scrubbed before validation/storage, including refusal and error metadata. Upload limits apply after ZIP expansion. Tests cover leaks, preservation, timestamp-shaped references, negative balances, mixed currencies, source collisions, malformed output, and API persistence: 59 pass. Browser checks cover the frontend and live Groq separately.

Scanned PDFs need OCR; addresses depend on labels; unusual IDs/layouts need more rules. Next I would add country-specific fixtures, OCR, migrations, and background analysis jobs.
